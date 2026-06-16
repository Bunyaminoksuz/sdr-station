"""
METEOR Autonomous Station — Central Configuration
All settings for the autonomous METEOR satellite reception system.
Multi-satellite support: M2-3 + M2-4 with priority-based scheduling.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# =============================================================================
# Project Paths
# =============================================================================
BASE_DIR = Path(__file__).parent.resolve()
PASSES_DIR = BASE_DIR / "passes"
TLE_DIR = BASE_DIR / "tle"
LOGS_DIR = BASE_DIR / "logs"
STATE_FILE = BASE_DIR / "run" / "state.json"
WEB_DIR = BASE_DIR / "web"

for d in [PASSES_DIR, TLE_DIR, LOGS_DIR, BASE_DIR / "run"]:
    d.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Satellite Configuration (Multi-Satellite)
# priority: 1 = highest, recorded first when passes overlap
# =============================================================================
SATELLITES = {
    "METEOR-M2-4": {
        "norad_id": 59051,
        "frequency": 137_900_000,       # 137.9 MHz
        "pipeline": "meteor_m2-x_lrpt",
        "priority": 1,
        "enabled": True,
    },
    "METEOR-M2-3": {
        "norad_id": 57166,
        "frequency": 137_900_000,       # 137.9 MHz
        "pipeline": "meteor_m2-x_lrpt",
        "priority": 2,
        "enabled": True,
    },
}

# Legacy single-satellite references (for backward compat)
SATELLITE_NAME = "METEOR-M2-4"
NORAD_ID = 59051
METEOR_FREQ = 137_900_000          # 137.9 MHz (düzeltildi: eski 137.1 yanlıştı)

# SDR Settings (shared across all satellites)
SAMPLE_RATE = 960_000           # 960 kHz (RTL-SDR Blog V4 minimum — 900k desteklemiyor!)
GAIN = 44                       # RTL-SDR gain (dB) — kullanıcı tercihi: 43-48 arası
BIAS_TEE = False                # RTL-SDR Blog v4 bias tee
BIAS_TEE_LOCKED = True          # True = bias tee panelden değiştirilemez (güvenlik kilidi)

# =============================================================================
# Observer Location (Default: Istanbul, Turkey)
# =============================================================================
OBSERVER_LAT = 41.0082
OBSERVER_LON = 28.9784
OBSERVER_ALT = 50

USER_CONFIG_FILE = BASE_DIR / "user_config.json"

# =============================================================================
# Pass Prediction
# =============================================================================
MIN_ELEVATION = 15
PREDICTION_HOURS = 24
AOS_BUFFER_SEC = 30
LOS_BUFFER_SEC = 30
TLE_UPDATE_INTERVAL = 12 * 3600

# =============================================================================
# TLE Sources (all weather satellites — covers both M2-3 and M2-4)
# =============================================================================
TLE_URLS = [
    "https://celestrak.org/NORAD/elements/weather.txt",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle",
    "https://www.amsat.org/tle/current/nasabare.txt",
]
TLE_FILE = TLE_DIR / "meteor_tle.txt"

# =============================================================================
# satdump Configuration
# =============================================================================
SATDUMP_BIN = "satdump"
DECODE_TIMEOUT_SEC = 1200           # 20 dakika — Pi 3B+ satdump decode süresi (30+ composite)

# =============================================================================
# Pi 3B+ Resource Optimization (1GB RAM / 4 cores)
# =============================================================================
SATDUMP_THREADS = 2
SCHEDULER_NICE = 10
RECORDING_NICE = 5
WEB_WORKERS = 1
ENABLE_SWAP = True
SWAP_SIZE_MB = 1024             # 1GB swap (SatDump decode anlık 400-500MB kullanabilir)

# =============================================================================
# IQ Baseband Recording
# =============================================================================
SAVE_BASEBAND = True
BASEBAND_DELETE_DAYS = 2

# =============================================================================
# Disk Management
# =============================================================================
MIN_FREE_DISK_GB = 2.0
EMERGENCY_CLEANUP_PERCENT = 90
AUTO_DELETE_DAYS = 30
DELETE_AFTER_DOWNLOAD = False

# =============================================================================
# Web Panel
# =============================================================================
WEB_HOST = "0.0.0.0"
WEB_PORT = 8080

# =============================================================================
# Logging
# =============================================================================
LOG_FILE = LOGS_DIR / "meteor_station.log"
LOG_LEVEL = "INFO"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 2

# =============================================================================
# Logging Factory
# =============================================================================
def get_logger(name: str) -> logging.Logger:
    """Create a configured logger. Replaces copy-pasted setup across modules."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(getattr(logging, LOG_LEVEL))
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        fh = RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


# =============================================================================
# Helpers
# =============================================================================
def get_enabled_satellites() -> dict:
    """Return only enabled satellites, sorted by priority."""
    return dict(
        sorted(
            [(k, v) for k, v in SATELLITES.items() if v.get("enabled", True)],
            key=lambda x: x[1]["priority"]
        )
    )


def load_user_config():
    """Load user configuration overrides from user_config.json."""
    import json
    global OBSERVER_LAT, OBSERVER_LON, OBSERVER_ALT
    global MIN_ELEVATION, AUTO_DELETE_DAYS, DELETE_AFTER_DOWNLOAD
    global BIAS_TEE, GAIN, SATELLITES

    if USER_CONFIG_FILE.exists():
        try:
            with open(USER_CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            OBSERVER_LAT = cfg.get("observer_lat", OBSERVER_LAT)
            OBSERVER_LON = cfg.get("observer_lon", OBSERVER_LON)
            OBSERVER_ALT = cfg.get("observer_alt", OBSERVER_ALT)
            MIN_ELEVATION = cfg.get("min_elevation", MIN_ELEVATION)
            AUTO_DELETE_DAYS = cfg.get("auto_delete_days", AUTO_DELETE_DAYS)
            DELETE_AFTER_DOWNLOAD = cfg.get("delete_after_download", DELETE_AFTER_DOWNLOAD)
            GAIN = cfg.get("gain", GAIN)

            # Bias-T güvenlik kilidi: BIAS_TEE_LOCKED=True ise config'den okunan değeri yoksay
            if BIAS_TEE_LOCKED:
                BIAS_TEE = False  # Güvenlik: her zaman kapalı
            else:
                BIAS_TEE = cfg.get("bias_tee", BIAS_TEE)

            # Load satellite toggles
            sat_cfg = cfg.get("satellites", {})
            for name, settings in sat_cfg.items():
                if name in SATELLITES:
                    if "enabled" in settings:
                        SATELLITES[name]["enabled"] = settings["enabled"]
                    if "priority" in settings:
                        SATELLITES[name]["priority"] = settings["priority"]
        except Exception as e:
            logging.getLogger("meteor-config").debug(f"User config load failed: {e}")


def save_user_config():
    """Save current user-configurable settings to user_config.json."""
    import json
    cfg = {
        "observer_lat": OBSERVER_LAT,
        "observer_lon": OBSERVER_LON,
        "observer_alt": OBSERVER_ALT,
        "min_elevation": MIN_ELEVATION,
        "auto_delete_days": AUTO_DELETE_DAYS,
        "delete_after_download": DELETE_AFTER_DOWNLOAD,
        "bias_tee": BIAS_TEE,
        "gain": GAIN,
        "satellites": {
            name: {"enabled": s["enabled"], "priority": s["priority"]}
            for name, s in SATELLITES.items()
        },
    }
    tmp_file = USER_CONFIG_FILE.with_suffix(".json.tmp")
    try:
        with open(tmp_file, "w") as f:
            json.dump(cfg, f, indent=2)
        tmp_file.replace(USER_CONFIG_FILE)
    except Exception as e:
        logging.getLogger("meteor-config").error(f"Failed to save user config: {e}")


# Load overrides on import
load_user_config()
