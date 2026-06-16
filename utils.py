"""
METEOR Autonomous Station — Utility Functions
Pure helper functions for data processing, metadata extraction, and telemetry parsing.
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone

import config

logger = config.get_logger("meteor-utils")

def detect_satellite(pass_dir: Path) -> dict:
    """Unified satellite detection: metadata.json → dataset.json → folder name."""
    meta = {}

    # 1) metadata.json
    meta_file = pass_dir / "metadata.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r") as f:
                meta = json.load(f)
        except Exception as e:
            logger.debug(f"metadata.json parse failed for {pass_dir.name}: {e}")

    # 2) dataset.json fallback
    if not meta.get("satellite"):
        for ds_path in [pass_dir / "dataset.json", pass_dir / "output" / "dataset.json"]:
            if ds_path.exists():
                try:
                    with open(ds_path, "r") as f:
                        ds = json.load(f)
                    sat_name = ds.get("satellite", ds.get("name", ""))
                    norad = ds.get("norad", 0)
                    if "M2-3" in sat_name or norad == 57166:
                        meta["satellite"] = "METEOR-M2-3"
                    elif "M2-4" in sat_name or norad == 59051:
                        meta["satellite"] = "METEOR-M2-4"
                    else:
                        meta.setdefault("satellite", sat_name or "Manuel Test")
                    meta.setdefault("frequency_mhz", 137.9)
                    # Timestamp
                    if ds.get("timestamp"):
                        try:
                            ts_dt = datetime.fromtimestamp(ds["timestamp"], tz=timezone.utc)
                            meta.setdefault("aos", ts_dt.isoformat())
                            meta.setdefault("recorded_at", ts_dt.isoformat())
                            meta["_ds_date"] = ts_dt.strftime("%Y-%m-%d")
                        except Exception:
                            pass
                    if not meta.get("success"):
                        meta["success"] = True
                except Exception as e:
                    logger.debug(f"dataset.json parse failed for {pass_dir.name}: {e}")
                break

    # 3) Folder name fallback
    if not meta.get("satellite"):
        if "M2-4" in pass_dir.name:
            meta["satellite"] = "METEOR-M2-4"
        elif "M2-3" in pass_dir.name:
            meta["satellite"] = "METEOR-M2-3"
        else:
            meta["satellite"] = "Manuel Test"
            meta["_manual"] = True

    # AOS fallback from folder name
    if not meta.get("aos"):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})[_T](\d{2})(\d{2})(\d{2})?", pass_dir.name)
        if m:
            meta["aos"] = (
                f"{m.group(1)}-{m.group(2)}-{m.group(3)}T"
                f"{m.group(4)}:{m.group(5)}:{m.group(6) or '00'}+00:00"
            )

    return meta


def extract_date(folder_name: str, metadata: dict) -> str:
    """Extract date from folder name or metadata for grouping."""
    # Try standard pattern: YYYY-MM-DD_HH-MM-SS_...
    m = re.match(r"(\d{4}-\d{2}-\d{2})", folder_name)
    if m:
        return m.group(1)
    # Try dataset.json timestamp
    if metadata.get("_ds_date"):
        return metadata["_ds_date"]
    # Try recorded_at from metadata
    if metadata.get("recorded_at"):
        return metadata["recorded_at"][:10]
    # Fallback
    return "Manuel Kayıtlar"


def file_type(suffix: str) -> str:
    """Determine file type category based on extension."""
    suffix = suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}:
        return "image"
    elif suffix == ".raw":
        return "baseband"
    elif suffix == ".json":
        return "metadata"
    elif suffix == ".log":
        return "log"
    else:
        return "other"


def parse_telemetry(tl_data: list) -> dict:
    """Parse telemetry.json array into a compact summary with averages."""
    if not tl_data or not isinstance(tl_data, list):
        return {}

    # MSU-MR ID ve mod — ilk entry'den al
    msu_mr_id = None
    msu_mr_set = None
    for entry in tl_data:
        if "msu_mr_id" in entry:
            msu_mr_id = entry["msu_mr_id"]
            msu_mr_set = entry.get("msu_mr_set", "?")
            break

    # analog_tlm içeren entry'leri topla
    tlm_entries = [e["analog_tlm"] for e in tl_data if "analog_tlm" in e]
    if not tlm_entries:
        return {"msu_mr_id": msu_mr_id, "msu_mr_set": msu_mr_set, "has_analog": False}

    def avg_kwd(*words):
        vals = []
        for e in tlm_entries:
            for k, v in e.items():
                if all(w.lower() in k.lower() for w in words):
                    if isinstance(v, (int, float)):
                        vals.append(v)
        return round(sum(vals) / len(vals), 2) if vals else None

    def kelvin_to_c(k):
        return round(k - 273.15, 1) if k is not None else None

    return {
        "msu_mr_id": msu_mr_id,
        "msu_mr_set": msu_mr_set,
        "has_analog": True,
        "sample_count": len(tlm_entries),
        # Sıcaklıklar (ham ADC)
        "baseplate_temp": avg_kwd("baseplate", "temperature"),
        "detector_ch3": avg_kwd("detector", "temperature", "3"),
        "detector_ch5": avg_kwd("detector", "temperature", "5"),
        "detector_ch6": avg_kwd("detector", "temperature", "6"),
        # Kalibrasyon (Kelvin -> Celsius)
        "cold_body_1_c": kelvin_to_c(avg_kwd("cold body", "temperature", "1")),
        "cold_body_2_c": kelvin_to_c(avg_kwd("cold body", "temperature", "2")),
        "cold_body_3_c": kelvin_to_c(avg_kwd("cold body", "temperature", "3")),
        "hot_body_1_c": kelvin_to_c(avg_kwd("hot body", "temperature", "1")),
        "hot_body_2_c": kelvin_to_c(avg_kwd("hot body", "temperature", "2")),
        "hot_body_3_c": kelvin_to_c(avg_kwd("hot body", "temperature", "3")),
        # Güç ve Optik (ham)
        "hv_vk1": avg_kwd("high voltage", "vk1"),
        "hv_vk2": avg_kwd("high voltage", "vk2"),
        "ir_lens_temp": avg_kwd("ir lens", "temperature"),
        "lamp_ch1": avg_kwd("lamp current", "1"),
        "lamp_ch2": avg_kwd("lamp current", "2"),
        "lamp_ch3": avg_kwd("lamp current", "3"),
    }
