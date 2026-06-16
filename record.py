#!/usr/bin/env python3
"""
METEOR Autonomous Station — Recording Script
Wraps satdump live pipeline for a single satellite pass.
Called by scheduler.py with pass info as JSON argument.
"""

import json
import os
import gc
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import config
import database

# =============================================================================
# Logging
# =============================================================================
logger = config.get_logger("meteor-record")


# =============================================================================
# Disk Check
# =============================================================================
def check_disk_space() -> bool:
    """Check if there's enough disk space to record."""
    usage = shutil.disk_usage(str(config.PASSES_DIR))
    free_gb = usage.free / (1024 ** 3)
    logger.info(f"Disk space: {free_gb:.2f} GB free")

    if free_gb < config.MIN_FREE_DISK_GB:
        logger.error(
            f"Insufficient disk space: {free_gb:.2f} GB < {config.MIN_FREE_DISK_GB} GB"
        )
        return False
    return True


def check_memory() -> bool:
    """Check if there's enough RAM to record (Pi 3B+ safety)."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        avail_mb = mem.available / (1024 ** 2)
        total_mb = mem.total / (1024 ** 2)
        logger.info(f"RAM: {avail_mb:.0f} MB available / {total_mb:.0f} MB total")

        # Need at least 200MB free for satdump
        if avail_mb < 200:
            logger.warning(f"Low RAM: {avail_mb:.0f} MB available. Running gc...")
            gc.collect()
            mem = psutil.virtual_memory()
            avail_mb = mem.available / (1024 ** 2)
            if avail_mb < 150:
                logger.error(f"Critically low RAM: {avail_mb:.0f} MB. Skipping recording.")
                return False
        return True
    except ImportError:
        return True  # psutil not available, proceed anyway


# =============================================================================
# Recording — Two-Step: rtl_sdr capture → satdump offline decode
# =============================================================================
def record_pass(pass_info: dict) -> bool:
    """
    Record a METEOR pass in two steps:
    1. Capture IQ baseband with rtl_sdr → .raw file (kept for BASEBAND_DELETE_DAYS)
    2. Decode with satdump offline → PNG images
    Returns True if recording produced images.
    """
    # Parse pass info
    def _parse_dt(v):
        return datetime.fromisoformat(v) if isinstance(v, str) else v

    aos_dt = _parse_dt(pass_info["aos"])
    los_dt = _parse_dt(pass_info["los"])

    duration_sec = pass_info.get("duration_sec", 900)
    max_elev = pass_info.get("max_elevation", 0)
    satellite = pass_info.get("satellite", config.SATELLITE_NAME)

    # Per-satellite frequency and pipeline (from scheduler)
    frequency = pass_info.get("frequency", config.METEOR_FREQ)
    pipeline = pass_info.get("pipeline", "meteor_m2-x_lrpt")

    # Total recording time with buffers
    total_timeout = duration_sec + config.AOS_BUFFER_SEC + config.LOS_BUFFER_SEC

    # Create output directory
    timestamp_str = aos_dt.strftime("%Y-%m-%d_%H%M%S")
    pass_dir_name = f"{timestamp_str}_{satellite.replace(' ', '-')}"
    pass_dir = config.PASSES_DIR / pass_dir_name

    # Üzerine yazma önleme: dizin varsa suffix ekle
    if pass_dir.exists():
        for suffix_num in range(2, 100):
            alt_dir = config.PASSES_DIR / f"{pass_dir_name}_{suffix_num}"
            if not alt_dir.exists():
                pass_dir = alt_dir
                break

    pass_dir.mkdir(parents=True, exist_ok=True)

    # IQ baseband file path — unique naming
    bb_name = f"{timestamp_str}_{satellite.replace(' ', '-')}_baseband.raw"
    iq_file = pass_dir / bb_name

    # Estimate IQ file size
    iq_size_mb = (config.SAMPLE_RATE * 2 * total_timeout) / (1024 ** 2)

    logger.info("=" * 60)
    logger.info(f"RECORDING: {satellite}")
    logger.info(f"  AOS: {aos_dt}")
    logger.info(f"  LOS: {los_dt}")
    logger.info(f"  Duration: {duration_sec}s (+{config.AOS_BUFFER_SEC + config.LOS_BUFFER_SEC}s buffer)")
    logger.info(f"  Max Elevation: {max_elev:.1f}°")
    logger.info(f"  Output: {pass_dir}")
    logger.info(f"  Frequency: {frequency / 1e6} MHz")
    logger.info(f"  Pipeline: {pipeline}")
    logger.info(f"  Sample Rate: {config.SAMPLE_RATE / 1e3} kHz")
    logger.info(f"  Gain: {config.GAIN} dB")
    logger.info(f"  Save Baseband: {config.SAVE_BASEBAND} (~{iq_size_mb:.0f} MB)")
    logger.info("=" * 60)

    # Set process priority (nice)
    try:
        os.nice(config.RECORDING_NICE)
        logger.info(f"Process nice set to {config.RECORDING_NICE}")
    except (OSError, AttributeError):
        pass

    import time as _time
    # ─── STEP 1: Capture IQ baseband with rtl_sdr ───
    logger.info("── STEP 1: IQ Baseband kaydı başlıyor ──")

    # Number of samples to capture
    num_samples = config.SAMPLE_RATE * total_timeout

    rtl_cmd = [
        "rtl_sdr",
        "-f", str(frequency),    # Tam merkez frekans (DC spike -> --dc_block ile temizlenir)
        "-s", str(config.SAMPLE_RATE),
        "-g", str(config.GAIN),
        "-n", str(num_samples),
    ]

    if config.BIAS_TEE:
        rtl_cmd.extend(["-T"])  # Enable bias tee

    rtl_cmd.append(str(iq_file))

    logger.info(f"  rtl_sdr komutu: {' '.join(rtl_cmd)}")

    iq_success = False
    max_retries = 3
    
    for attempt in range(1, max_retries + 1):
        try:
            start_time = _time.time()
            process = subprocess.run(
                rtl_cmd,
                capture_output=True,
                text=True,
                timeout=total_timeout + 60,
            )
            elapsed = _time.time() - start_time
            
            if process.returncode == 0 and iq_file.exists():
                iq_size_actual = iq_file.stat().st_size / (1024 ** 2)
                
                # Corrupt IQ Detection (Bozuk Veri Kontrolü)
                # Beklenen Boyut: samplerate * süre * 2 (1 byte I, 1 byte Q)
                expected_mb = (config.SAMPLE_RATE * total_timeout * 2) / (1024 ** 2)
                
                # Eğer kaydedilen veri, beklenen teorik boyutun %80'inden küçükse kayıt hatalıdır.
                if iq_size_actual < expected_mb * 0.8:
                    logger.error(f"  ❌ IQ kaydı bozuk! Beklenen: ~{expected_mb:.1f} MB, Gelen: {iq_size_actual:.1f} MB")
                    iq_success = False
                    break # Uzun sürdüğü için tekrar denemeye gerek yok.
                
                logger.info(f"  ✅ IQ kaydı tamamlandı: {iq_size_actual:.1f} MB")
                iq_success = True
                break
            else:
                logger.error(f"  ❌ rtl_sdr hata (exit code: {process.returncode})")
                if process.stderr:
                    logger.error(f"  stderr: {process.stderr[:200]}")
                
                # İlk 15 saniyede çökerse (USB claim lock) USB'yi bekleyip tekrar dene.
                if elapsed < 15 and attempt < max_retries:
                    logger.warning(f"  ⚠️ rtl_sdr hemen çöktü (USB kilitlenmesi). 3sn bekleniyor... (Deneme {attempt}/{max_retries})")
                    _time.sleep(3)
                else:
                    break
                    
        except subprocess.TimeoutExpired:
            logger.error("  ❌ rtl_sdr timeout!")
            break
        except FileNotFoundError:
            logger.error("  ❌ rtl_sdr bulunamadı! 'apt install rtl-sdr' ile kur")
            break
        except Exception as e:
            logger.error(f"  ❌ rtl_sdr hatası: {e}")
            break

    if not iq_success:
        # IQ kaydı başarısız — metadata yaz ve veritabanını güncelle
        _write_metadata(pass_dir, pass_info, success=False, exit_code=-10,
                        images=[], has_baseband=False)
        database.sync_pass_directory(pass_dir)
        return False

    # ─── STEP 2: Decode with satdump (offline) ───
    import time as _time

    # Belleği serbest bırak — Pi 3B+ 1GB RAM için kritik
    gc.collect()

    logger.info("── STEP 2: Kayıt sonrası 10s bekleniyor (IO flush) ──")
    _time.sleep(10)
    logger.info("── STEP 2: satdump ile decode başlıyor ──")

    # Çıkış dizini: pass_dir içinde ayrı bir klasör (baseband ile çakışma önlenir)
    decode_output = pass_dir / "output"
    decode_output.mkdir(parents=True, exist_ok=True)

    decode_cmd = [
        config.SATDUMP_BIN,
        pipeline,                # Pipeline adı (meteor_m2-x_lrpt)
        "baseband",              # Input seviyesi: ham baseband
        str(iq_file),            # Giriş dosyası
        str(decode_output),      # Çıkış dizini (alt klasör)
        "--samplerate", str(config.SAMPLE_RATE),
        "--baseband_format", "cu8",  # rtl_sdr unsigned 8-bit IQ formatı
        "--dc_block",            # Merkez frekanstaki DC spike'ı filtrele
        "--fill_missing",        # Kayıp paketleri (siyah satırları) telafi et
    ]

    logger.info(f"  satdump komutu: {' '.join(decode_cmd)}")
    logger.info(f"  Decode timeout: {config.DECODE_TIMEOUT_SEC}s ({config.DECODE_TIMEOUT_SEC // 60}dk)")

    decode_start = _time.time()
    exit_code = -1
    try:
        process = subprocess.Popen(
            decode_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Stream output to log in a separate thread to avoid deadlock
        decode_log_path = pass_dir / "decode.log"
        decode_lines = []

        def _drain_stdout():
            try:
                with open(decode_log_path, "w") as log_file:
                    for line in process.stdout:
                        line = line.rstrip()
                        if line:
                            logger.debug(f"  satdump: {line}")
                            log_file.write(line + "\n")
                            decode_lines.append(line)
            except Exception as e:
                logger.warning(f"  satdump log drain error: {e}")

        drain_thread = threading.Thread(target=_drain_stdout, daemon=True)
        drain_thread.start()

        # Wait with proper timeout
        process.wait(timeout=config.DECODE_TIMEOUT_SEC)
        drain_thread.join(timeout=10)  # Give 10s for remaining output
        exit_code = process.returncode
        decode_elapsed = _time.time() - decode_start
        logger.info(f"  satdump çıkış kodu: {exit_code} (süre: {decode_elapsed:.0f}s)")

    except subprocess.TimeoutExpired:
        decode_elapsed = _time.time() - decode_start
        logger.error(f"  satdump timeout ({decode_elapsed:.0f}s), güvenli kapatma deneniyor (SIGTERM)...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.error("  satdump kapanmadı, zorla öldürülüyor (SIGKILL)...")
            process.kill()
            process.wait()
        exit_code = -1
    except FileNotFoundError:
        logger.error(f"  satdump bulunamadı! '{config.SATDUMP_BIN}' PATH'de mi?")
        exit_code = -2
    except Exception as e:
        logger.error(f"  satdump hatası: {e}")
        exit_code = -3

    # ─── Results ───
    images = find_images(pass_dir)
    success = len(images) > 0

    # Handle baseband file
    has_baseband = iq_file.exists()
    if has_baseband and not config.SAVE_BASEBAND:
        # User doesn't want to keep baseband
        logger.info("  Baseband kaydı siliniyor (SAVE_BASEBAND=False)")
        iq_file.unlink()
        has_baseband = False

    if has_baseband:
        iq_size_final = iq_file.stat().st_size / (1024 ** 2)
        logger.info(f"  📦 Baseband saklanıyor: {iq_size_final:.1f} MB ({config.BASEBAND_DELETE_DAYS} gün)")

    # ─── Parse decode log for SNR & frame stats ───
    decode_stats = _parse_decode_log(pass_dir / "decode.log")

    # Write metadata
    _write_metadata(pass_dir, pass_info, success=success, exit_code=exit_code,
                    images=images, has_baseband=has_baseband, decode_stats=decode_stats)

    if success:
        logger.info(f"✅ BAŞARILI — {len(images)} görüntü + {'IQ baseband' if has_baseband else 'baseband yok'}")
        for img in images:
            size_kb = img.stat().st_size / 1024
            logger.info(f"    🖼️ {img.name} ({size_kb:.0f} KB)")
        if decode_stats.get("snr_avg"):
            logger.info(f"    📊 SNR: avg={decode_stats['snr_avg']:.1f} dB, peak={decode_stats['snr_peak']:.1f} dB")
    else:
        logger.warning("⚠️ Decode tamamlandı ama görüntü üretilemedi")

    # Clean up intermediate satdump files (keep .raw baseband and images)
    cleanup_intermediate(pass_dir)

    # İşlemler bitince pass'i SQLite veritabanına senkronize et
    database.sync_pass_directory(pass_dir)

    return success


def _parse_decode_log(log_path):
    """Parse SatDump decode.log for SNR history, Viterbi BER, and frame stats."""
    import re
    stats = {
        "snr_history": [],
        "snr_avg": None,
        "snr_peak": None,
        "viterbi_ber": [],
        "viterbi_avg": None,
        "deframer_synced": 0,
        "deframer_nosync": 0,
    }

    if not log_path.exists():
        return stats

    try:
        with open(log_path, "r") as f:
            lines = f.readlines()

        # SatDump v1.2.2 log format examples:
        # (I) CCSDS SNR : 12.3 dB
        # (I) SNR : 8.5 dB
        # (I) Vit BER : 0.002
        # (I) Viterbi BER : 0.003
        # (I) Reed-Solomon ...
        # (I) Deframer : synced
        # (I) Deframer : nosync

        snr_pattern = re.compile(r"SNR\s*:\s*([\d.]+)\s*dB", re.IGNORECASE)
        ber_pattern = re.compile(r"(?:Vit(?:erbi)?)\s*BER\s*:\s*([\d.]+)", re.IGNORECASE)
        deframer_pattern = re.compile(r"Deframer\s*:\s*(\w+)", re.IGNORECASE)

        for line in lines:
            # SNR
            m = snr_pattern.search(line)
            if m:
                snr = float(m.group(1))
                stats["snr_history"].append(round(snr, 1))

            # Viterbi BER
            m = ber_pattern.search(line)
            if m:
                ber = float(m.group(1))
                stats["viterbi_ber"].append(round(ber, 4))

            # Deframer
            m = deframer_pattern.search(line)
            if m:
                state = m.group(1).lower()
                if "sync" in state and "nosync" not in state:
                    stats["deframer_synced"] += 1
                else:
                    stats["deframer_nosync"] += 1

        # Calculate averages
        if stats["snr_history"]:
            stats["snr_avg"] = round(sum(stats["snr_history"]) / len(stats["snr_history"]), 1)
            stats["snr_peak"] = round(max(stats["snr_history"]), 1)

        if stats["viterbi_ber"]:
            stats["viterbi_avg"] = round(sum(stats["viterbi_ber"]) / len(stats["viterbi_ber"]), 4)

    except Exception as e:
        logger.debug(f"Decode log parse error: {e}")

    return stats


def _write_metadata(pass_dir, pass_info, success, exit_code, images, has_baseband, decode_stats=None):
    """Write pass metadata to JSON file."""
    # Baseband dosyasını dinamik bul (yeni isimlendirme desteği)
    iq_files = list(pass_dir.glob("*_baseband.raw")) + list(pass_dir.glob("baseband.raw"))
    iq_file = iq_files[0] if iq_files else None

    metadata = {
        "satellite": pass_info.get("satellite", config.SATELLITE_NAME),
        "aos": str(pass_info.get("aos", "")),
        "los": str(pass_info.get("los", "")),
        "duration_sec": pass_info.get("duration_sec", 0),
        "max_elevation": round(pass_info.get("max_elevation", 0), 1),
        "frequency_mhz": pass_info.get("frequency", config.METEOR_FREQ) / 1e6,
        "pipeline": pass_info.get("pipeline", "meteor_m2-x_lrpt"),
        "sample_rate_khz": config.SAMPLE_RATE / 1e3,
        "gain_db": config.GAIN,
        "threads": config.SATDUMP_THREADS,
        "success": success,
        "exit_code": exit_code,
        "images": [img.name for img in images] if images else [],
        "has_baseband": has_baseband,
        "baseband_file": iq_file.name if iq_file else None,
        "baseband_size_mb": round(iq_file.stat().st_size / (1024 ** 2), 1) if iq_file and iq_file.exists() else 0,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "downloaded": False,
        "observer": {
            "lat": config.OBSERVER_LAT,
            "lon": config.OBSERVER_LON,
            "alt": config.OBSERVER_ALT,
        },
    }

    # Add decode stats (SNR, BER, frame sync)
    if decode_stats:
        metadata["snr_avg"] = decode_stats.get("snr_avg")
        metadata["snr_peak"] = decode_stats.get("snr_peak")
        metadata["snr_history"] = decode_stats.get("snr_history", [])
        metadata["viterbi_avg"] = decode_stats.get("viterbi_avg")
        metadata["deframer_synced"] = decode_stats.get("deframer_synced", 0)
        metadata["deframer_nosync"] = decode_stats.get("deframer_nosync", 0)

    with open(pass_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)


def find_images(pass_dir: Path) -> list:
    """Find all image files in the pass directory."""
    image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}
    images = []
    for f in pass_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in image_extensions:
            images.append(f)
    return sorted(images)


def cleanup_intermediate(pass_dir: Path):
    """Remove intermediate satdump files to save disk space.
    NOTE: baseband.raw is preserved (managed by cleanup.py separately)."""
    intermediate_extensions = {".cadu", ".frm", ".soft", ".bin", ".s", ".dat"}
    removed_size = 0

    for f in pass_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in intermediate_extensions:
            size = f.stat().st_size
            try:
                f.unlink()
                removed_size += size
                logger.debug(f"  Cleaned: {f.name} ({size / 1024 / 1024:.1f} MB)")
            except Exception as e:
                logger.warning(f"  Failed to clean {f.name}: {e}")

    if removed_size > 0:
        logger.info(
            f"Cleaned {removed_size / 1024 / 1024:.1f} MB of intermediate files"
        )


# =============================================================================
# Main
# =============================================================================
def main():
    if len(sys.argv) < 2:
        print("Usage: record.py '<pass_info_json>'")
        sys.exit(1)

    try:
        pass_info = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON argument: {e}")
        sys.exit(1)

    if not check_disk_space():
        sys.exit(2)

    if not check_memory():
        sys.exit(4)

    # Free memory before recording
    gc.collect()

    success = record_pass(pass_info)
    sys.exit(0 if success else 3)


if __name__ == "__main__":
    main()
