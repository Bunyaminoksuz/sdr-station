#!/usr/bin/env python3
"""
METEOR Autonomous Station — Web Panel (FastAPI)
Serves dashboard, gallery (date-grouped), pass detail, bulk download, and API.
Multi-satellite support with satellite filtering.
"""

import json
import io
import logging
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import OrderedDict

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, validator
from typing import Optional

import config
import database

logger = config.get_logger("meteor-web")

# =============================================================================
# App Setup
# =============================================================================
app = FastAPI(title="METEOR Station", version="2.0")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# =============================================================================
# Models
# =============================================================================
class ConfigUpdate(BaseModel):
    observer_lat: Optional[float] = None
    observer_lon: Optional[float] = None
    observer_alt: Optional[float] = None
    min_elevation: Optional[int] = None
    auto_delete_days: Optional[int] = None
    delete_after_download: Optional[bool] = None
    gain: Optional[int] = None
    bias_tee: Optional[bool] = None
    bias_tee_confirm: Optional[bool] = None  # Çift onay: bias_tee=True için bu da True olmalı
    satellites: Optional[dict] = None

    @validator("observer_lat")
    def lat_range(cls, v):
        if v is not None and not (-90 <= v <= 90):
            raise ValueError("observer_lat must be between -90 and 90")
        return v

    @validator("observer_lon")
    def lon_range(cls, v):
        if v is not None and not (-180 <= v <= 180):
            raise ValueError("observer_lon must be between -180 and 180")
        return v

    @validator("min_elevation")
    def elev_range(cls, v):
        if v is not None and not (0 <= v <= 90):
            raise ValueError("min_elevation must be between 0 and 90")
        return v

    @validator("gain")
    def gain_range(cls, v):
        if v is not None and not (0 <= v <= 49):
            raise ValueError("gain must be between 0 and 49")
        return v

    @validator("auto_delete_days")
    def delete_days_range(cls, v):
        if v is not None and not (1 <= v <= 365):
            raise ValueError("auto_delete_days must be between 1 and 365")
        return v


# =============================================================================
# Security Helpers
# =============================================================================
def _safe_pass_path(pass_id: str, *sub: str) -> Path:
    """Resolve a path within PASSES_DIR, preventing path traversal."""
    file_path = (config.PASSES_DIR / pass_id / Path(*sub) if sub
                 else config.PASSES_DIR / pass_id).resolve()
    passes_root = config.PASSES_DIR.resolve()
    if not str(file_path).startswith(str(passes_root)):
        raise HTTPException(status_code=403, detail="Access denied")
    return file_path


# =============================================================================
# Satellite Detection Helper (deduplicated)
# =============================================================================
from utils import detect_satellite, extract_date, file_type, parse_telemetry


# =============================================================================
# Pages
# =============================================================================
@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


# =============================================================================
# System Status API
# =============================================================================
@app.get("/api/status")
async def get_status():
    """System status: disk, CPU, memory, temperature, scheduler state."""
    import psutil

    # Disk
    usage = shutil.disk_usage(str(config.PASSES_DIR))
    disk = {
        "total_gb": round(usage.total / (1024 ** 3), 1),
        "used_gb": round(usage.used / (1024 ** 3), 1),
        "free_gb": round(usage.free / (1024 ** 3), 1),
        "percent_used": round((usage.used / usage.total) * 100, 1),
    }

    # System
    cpu_temp = None
    try:
        temps = psutil.sensors_temperatures()
        if "cpu_thermal" in temps:
            cpu_temp = temps["cpu_thermal"][0].current
        elif "coretemp" in temps:
            cpu_temp = temps["coretemp"][0].current
    except Exception:
        pass  # Temperature sensors not available on all platforms

    system = {
        "cpu_percent": psutil.cpu_percent(interval=0),
        "memory_percent": round(psutil.virtual_memory().percent, 1),
        "memory_available_mb": round(psutil.virtual_memory().available / (1024 ** 2)),
        "cpu_temp": cpu_temp,
        "uptime": _format_uptime(),
    }

    # Scheduler state
    station = {"status": "unknown", "image_count": 0, "pass_count": 0}
    state_data = {}
    try:
        if config.STATE_FILE.exists():
            with open(config.STATE_FILE, "r") as f:
                state_data = json.load(f)
            station.update(state_data)
    except Exception as e:
        logger.debug(f"State file read error: {e}")

    # Count images and passes from database instead of full FS scan
    pass_count = 0
    image_count = 0
    last_decode = None
    
    try:
        passes_db = database.get_passes()
        pass_count = len(passes_db)
        image_count = sum(len(p.get("images", [])) for p in passes_db)
        
        # En son başarılı pass'ı bul
        for p in passes_db:
            has_images = len(p.get("images", [])) > 0
            is_success = p.get("metadata", {}).get("success", False)
            if has_images and not is_success:
                is_success = True
                
            if not is_success:
                continue
                
            meta = p["metadata"]
            
            last_decode = {
                "pass_id": p["id"],
                "satellite": p["satellite"],
                "time": meta.get("aos", meta.get("recorded_at", "")),
                "max_elevation": meta.get("max_elevation", 0),
                "frequency_mhz": meta.get("frequency_mhz", "?"),
                "norad": meta.get("norad_id", "?"),
                "sat_name": p["satellite"],
                "telemetry_summary": p.get("telemetry", {}),
                "channel_count": len(p.get("images", [])),
            }
            break
    except Exception as e:
        logger.error(f"Database query error in get_status: {e}")

    station["image_count"] = image_count
    station["pass_count"] = pass_count

    # Sun info (already in state_data)
    sun = state_data.get("sun", {"sunrise": None, "sunset": None, "is_daylight": None})

    return {"disk": disk, "system": system, "station": station, "sun": sun, "last_decode": last_decode}


def _format_uptime():
    try:
        import psutil
        boot = datetime.fromtimestamp(psutil.boot_time())
        delta = datetime.now() - boot
        days = delta.days
        hours = delta.seconds // 3600
        mins = (delta.seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h {mins}m"
        return f"{hours}h {mins}m"
    except Exception:
        return "N/A"



# =============================================================================
# Passes API — Date Grouped
# =============================================================================
@app.get("/api/passes")
async def list_passes(satellite: Optional[str] = Query(None)):
    """List all passes grouped by date, optionally filtered by satellite."""
    passes_db = database.get_passes(satellite)
    
    # Group by date
    grouped = OrderedDict()
    for p in passes_db:
        date = p["date"]
        if date not in grouped:
            grouped[date] = {
                "date": date,
                "passes": [],
                "total_images": 0,
                "total_size_mb": 0,
            }
        grouped[date]["passes"].append(p)
        grouped[date]["total_images"] += len(p["images"])
        grouped[date]["total_size_mb"] += p["total_size_mb"]

    # Round sizes
    for g in grouped.values():
        g["total_size_mb"] = round(g["total_size_mb"], 1)

    return list(grouped.values())




# =============================================================================
# Pass Detail API
# =============================================================================
@app.get("/api/passes/{pass_id}/detail")
async def get_pass_detail(pass_id: str):
    """Get full detail of a pass: all files, metadata, decode settings."""
    pass_db = database.get_pass(pass_id)
    if not pass_db:
        raise HTTPException(status_code=404, detail="Pass not found")

    pass_dir = _safe_pass_path(pass_id)
    
    # Decode log
    decode_log = ""
    log_file = pass_dir / "decode.log"
    if log_file.exists():
        try:
            decode_log = log_file.read_text()[-5000:]  # Last 5KB of log
        except Exception:
            pass

    metadata = pass_db["metadata"]
    
    # Decode settings from metadata
    decode_settings = {
        "frequency_mhz": metadata.get("frequency_mhz"),
        "pipeline": metadata.get("pipeline"),
        "sample_rate_khz": metadata.get("sample_rate_khz"),
        "gain_db": metadata.get("gain_db"),
        "threads": metadata.get("threads"),
        "exit_code": metadata.get("exit_code"),
    }

    return {
        "id": pass_id,
        "metadata": metadata,
        "decode_settings": decode_settings,
        "decode_log": decode_log,
        "files": pass_db["files"],
    }


# =============================================================================
# File Serving (images, baseband, logs)
# =============================================================================
@app.get("/api/passes/{pass_id}/images/{filename:path}")
async def get_image(pass_id: str, filename: str):
    """Serve an image file."""
    file_path = _safe_pass_path(pass_id, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.get("/api/passes/{pass_id}/files/{filename:path}")
async def get_file(pass_id: str, filename: str):
    """Serve any file from a pass (images, baseband, logs, metadata)."""
    file_path = _safe_pass_path(pass_id, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Content type detection
    suffix = file_path.suffix.lower()
    media_types = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".json": "application/json", ".log": "text/plain", ".txt": "text/plain",
        ".raw": "application/octet-stream",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type, filename=file_path.name)


@app.get("/api/passes/{pass_id}/download/{filename:path}")
async def download_file(pass_id: str, filename: str):
    """Download a specific file."""
    file_path = _safe_pass_path(pass_id, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=file_path.name)


# =============================================================================
# Bulk Download (ZIP)
# =============================================================================
@app.get("/api/download/pass/{pass_id}")
def download_pass_zip(pass_id: str):
    """Download entire pass as ZIP."""
    pass_dir = _safe_pass_path(pass_id)
    if not pass_dir.exists():
        raise HTTPException(status_code=404, detail="Pass not found")
    return _create_zip_response([pass_dir], f"{pass_id}.zip")


@app.get("/api/download/daily/{date}")
def download_daily_zip(date: str, satellite: Optional[str] = Query(None)):
    """Download all passes for a specific date as ZIP. Format: 2026-02-28"""
    dirs = _get_dirs_for_date(date, satellite)
    if not dirs:
        raise HTTPException(status_code=404, detail="No passes for this date")
    return _create_zip_response(dirs, f"meteor_{date}.zip")


@app.get("/api/download/weekly/{year}/{week}")
def download_weekly_zip(year: int, week: int, satellite: Optional[str] = Query(None)):
    """Download all passes for a specific ISO week as ZIP."""
    dirs = _get_dirs_for_week(year, week, satellite)
    if not dirs:
        raise HTTPException(status_code=404, detail="No passes for this week")
    return _create_zip_response(dirs, f"meteor_{year}_W{week:02d}.zip")


@app.get("/api/download/monthly/{year}/{month}")
def download_monthly_zip(year: int, month: int, satellite: Optional[str] = Query(None)):
    """Download all passes for a specific month as ZIP."""
    dirs = _get_dirs_for_month(year, month, satellite)
    if not dirs:
        raise HTTPException(status_code=404, detail="No passes for this month")
    return _create_zip_response(dirs, f"meteor_{year}_{month:02d}.zip")


def _create_zip_response(directories: list, filename: str) -> StreamingResponse:
    """Create a streaming ZIP response from pass directories."""
    import tempfile
    import subprocess
    import shutil

    # OS 'zip' komutu varsa on-the-fly streaming kullan (sıfır disk IO)
    if shutil.which("zip"):
        pass_names = [d.name for d in directories]
        cmd = ["zip", "-0", "-q", "-r", "-"] + pass_names + ["-x", "*.soft", "*.cbor", "*.cadu"]
        
        proc = subprocess.Popen(
            cmd,
            cwd=str(config.PASSES_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        
        def iter_process():
            try:
                while True:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                proc.stdout.close()
                proc.wait()
                
        return StreamingResponse(
            iter_process(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # Fallback: zip komutu yoksa geçici dosyaya yaz (endpoints 'def' olduğu için API bloklanmaz)
    tmp = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
        for d in directories:
            for f in d.rglob("*"):
                if f.is_file():
                    if f.suffix.lower() in ('.soft', '.cbor', '.cadu'):
                        continue
                    arcname = f"{d.name}/{f.relative_to(d)}"
                    zf.write(f, arcname)
    tmp.seek(0)

    def iterfile():
        while True:
            chunk = tmp.read(65536)
            if not chunk:
                break
            yield chunk
        tmp.close()

    return StreamingResponse(
        iterfile(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _get_dirs_for_date(date_str: str, satellite: Optional[str] = None) -> list:
    """Get pass directories matching a date string (YYYY-MM-DD)."""
    passes_db = database.get_passes(satellite=satellite)
    dirs = []
    for p in passes_db:
        if p["date"] == date_str:
            d = config.PASSES_DIR / p["id"]
            if d.exists():
                dirs.append(d)
    return dirs


def _get_dirs_for_week(year: int, week: int, satellite: Optional[str] = None) -> list:
    """Get pass directories for an ISO week."""
    passes_db = database.get_passes(satellite=satellite)
    dirs = []
    for p in passes_db:
        try:
            dt = datetime.strptime(p["date"], "%Y-%m-%d")
            iso = dt.isocalendar()
            if iso[0] == year and iso[1] == week:
                d = config.PASSES_DIR / p["id"]
                if d.exists():
                    dirs.append(d)
        except ValueError:
            pass
    return dirs


def _get_dirs_for_month(year: int, month: int, satellite: Optional[str] = None) -> list:
    """Get pass directories for a month."""
    passes_db = database.get_passes(satellite=satellite)
    prefix = f"{year}-{month:02d}"
    dirs = []
    for p in passes_db:
        if p["date"].startswith(prefix):
            d = config.PASSES_DIR / p["id"]
            if d.exists():
                dirs.append(d)
    return dirs


# =============================================================================
# Delete Pass
# =============================================================================
@app.delete("/api/passes/{pass_id}")
async def delete_pass(pass_id: str):
    """Delete a recorded pass."""
    pass_dir = _safe_pass_path(pass_id)
    if not pass_dir.exists():
        raise HTTPException(status_code=404, detail="Pass not found")

    try:
        shutil.rmtree(pass_dir)
        return {"status": "deleted", "pass_id": pass_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Upcoming Passes API
# =============================================================================
@app.get("/api/upcoming")
async def get_upcoming():
    """Get upcoming passes from scheduler state."""
    try:
        if config.STATE_FILE.exists():
            with open(config.STATE_FILE, "r") as f:
                state = json.load(f)
            return {
                "next_pass": state.get("next_pass"),
                "upcoming_passes": state.get("upcoming_passes", []),
            }
    except Exception:
        pass
    return {"next_pass": None, "upcoming_passes": []}


# =============================================================================
# Satellites API
# =============================================================================
@app.get("/api/satellites")
async def get_satellites():
    """Get list of configured satellites with their settings."""
    sats = []
    for name, cfg in config.SATELLITES.items():
        sats.append({
            "name": name,
            "norad_id": cfg["norad_id"],
            "frequency_mhz": cfg["frequency"] / 1e6,
            "pipeline": cfg["pipeline"],
            "priority": cfg["priority"],
            "enabled": cfg.get("enabled", True),
        })
    sats.sort(key=lambda x: x["priority"])
    return sats


# =============================================================================
# Config API
# =============================================================================
@app.get("/api/config")
async def get_config():
    config.load_user_config()
    return {
        "observer_lat": config.OBSERVER_LAT,
        "observer_lon": config.OBSERVER_LON,
        "observer_alt": config.OBSERVER_ALT,
        "min_elevation": config.MIN_ELEVATION,
        "auto_delete_days": config.AUTO_DELETE_DAYS,
        "delete_after_download": config.DELETE_AFTER_DOWNLOAD,
        "gain": config.GAIN,
        "bias_tee": config.BIAS_TEE,
        "bias_tee_locked": config.BIAS_TEE_LOCKED,
        "save_baseband": config.SAVE_BASEBAND,
        "baseband_delete_days": config.BASEBAND_DELETE_DAYS,
        "satellites": {
            name: {"enabled": s["enabled"], "priority": s["priority"],
                    "frequency_mhz": s["frequency"] / 1e6, "norad_id": s["norad_id"]}
            for name, s in config.SATELLITES.items()
        },
    }


@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    config.load_user_config()

    if update.observer_lat is not None:
        config.OBSERVER_LAT = update.observer_lat
    if update.observer_lon is not None:
        config.OBSERVER_LON = update.observer_lon
    if update.observer_alt is not None:
        config.OBSERVER_ALT = update.observer_alt
    if update.min_elevation is not None:
        config.MIN_ELEVATION = update.min_elevation
    if update.auto_delete_days is not None:
        config.AUTO_DELETE_DAYS = update.auto_delete_days
    if update.delete_after_download is not None:
        config.DELETE_AFTER_DOWNLOAD = update.delete_after_download
    if update.gain is not None:
        config.GAIN = update.gain

    # Bias-T güvenlik kontrolü
    if update.bias_tee is not None:
        if update.bias_tee:
            # Bias-T açmak için çift onay gerekli VE güvenlik kilidi kapalı olmalı
            if config.BIAS_TEE_LOCKED:
                pass  # Kilitli: değiştirme
            elif update.bias_tee_confirm:
                config.BIAS_TEE = True
            # confirm yoksa sessizce yoksay
        else:
            config.BIAS_TEE = False  # Kapatmak her zaman serbest

    if update.satellites is not None:
        for name, settings in update.satellites.items():
            if name in config.SATELLITES:
                if "enabled" in settings:
                    config.SATELLITES[name]["enabled"] = settings["enabled"]
                if "priority" in settings:
                    config.SATELLITES[name]["priority"] = settings["priority"]

    config.save_user_config()
    return {
        "status": "updated",
        "bias_tee_locked": config.BIAS_TEE_LOCKED,
        "bias_tee": config.BIAS_TEE,
    }


# =============================================================================
# Run
# =============================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.WEB_HOST, port=config.WEB_PORT)
