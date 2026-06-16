#!/usr/bin/env python3
"""
METEOR Autonomous Station — Scheduler
Multi-satellite support with priority-based conflict resolution.
Downloads TLE, predicts passes for all enabled satellites, resolves conflicts,
and triggers recordings automatically.
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from skyfield.api import EarthSatellite, load, wgs84

import config

# =============================================================================
# Logging Setup
# =============================================================================
logger = config.get_logger("meteor-scheduler")

ts = load.timescale()


# =============================================================================
# State Management
# =============================================================================
def update_state(state_data: dict):
    """Write current state to state.json for the web panel atomically."""
    state_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        tmp_file = config.STATE_FILE.with_suffix(".json.tmp")
        with open(tmp_file, "w") as f:
            json.dump(state_data, f, indent=2, default=str)
        tmp_file.replace(config.STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to write state: {e}")


def get_state() -> dict:
    try:
        if config.STATE_FILE.exists():
            with open(config.STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"status": "unknown"}


# =============================================================================
# TLE Management (Multi-Satellite)
# =============================================================================
def download_tle() -> bool:
    """Download TLE data for all enabled satellites. Returns True if at least one succeeds."""
    logger.info("Updating TLE data for all satellites...")

    success = False
    for url in config.TLE_URLS:
        try:
            resp = requests.get(url, timeout=(10, 30), headers={
                "User-Agent": "MeteorStation/2.0 (Multi-Satellite Receiver)"
            })
            resp.raise_for_status()
            text = resp.text.strip()
            lines = text.splitlines()

            # Extract TLE for each enabled satellite
            satellites = config.get_enabled_satellites()
            found_any = False

            for sat_name, sat_cfg in satellites.items():
                norad_id = sat_cfg["norad_id"]
                tle_line1 = None
                tle_line2 = None
                name = None

                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith("1 ") and str(norad_id) in stripped[:10]:
                        tle_line1 = stripped
                        if i + 1 < len(lines):
                            tle_line2 = lines[i + 1].strip()
                        if i > 0 and not lines[i - 1].strip().startswith(("1 ", "2 ")):
                            name = lines[i - 1].strip()
                        break

                if tle_line1 and tle_line2:
                    tle_file = config.TLE_DIR / f"{sat_name.replace(' ', '_')}_tle.txt"
                    tle_content = f"{name or sat_name}\n{tle_line1}\n{tle_line2}\n"
                    with open(tle_file, "w") as f:
                        f.write(tle_content)
                    logger.info(f"  TLE updated: {sat_name} (NORAD {norad_id})")
                    found_any = True

            if found_any:
                success = True
                break  # Got TLEs from this source, no need for fallback

        except requests.exceptions.Timeout:
            logger.warning(f"TLE download timeout: {url}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"TLE connection error: {url}")
        except Exception as e:
            logger.warning(f"TLE download failed: {url}: {e}")

    if not success:
        # Check cached TLEs
        cached = any(
            (config.TLE_DIR / f"{name.replace(' ', '_')}_tle.txt").exists()
            for name in config.get_enabled_satellites()
        )
        if cached:
            logger.warning("All TLE sources failed, using cached TLE")
            return True
        logger.error("No TLE data available!")
        return False

    return True


def load_satellite(sat_name: str):
    """Load a satellite from its TLE file. Returns (EarthSatellite, name) or (None, None)."""
    tle_file = config.TLE_DIR / f"{sat_name.replace(' ', '_')}_tle.txt"

    # Fallback to legacy single TLE file
    if not tle_file.exists():
        tle_file = config.TLE_FILE
    if not tle_file.exists():
        return None, None

    try:
        lines = tle_file.read_text().strip().splitlines()
        if len(lines) >= 3:
            name = lines[0].strip()
            line1 = lines[1].strip()
            line2 = lines[2].strip()
        elif len(lines) == 2:
            name = sat_name
            line1 = lines[0].strip()
            line2 = lines[1].strip()
        else:
            return None, None

        satellite = EarthSatellite(line1, line2, name, ts)
        return satellite, name
    except Exception as e:
        logger.error(f"Failed to load TLE for {sat_name}: {e}")
        return None, None


# =============================================================================
# Pass Prediction (Multi-Satellite)
# =============================================================================
def predict_passes(hours_ahead: int = None) -> list:
    """
    Predict passes for ALL enabled satellites, then resolve conflicts.
    Returns a merged, conflict-free, time-sorted list.
    """
    if hours_ahead is None:
        hours_ahead = config.PREDICTION_HOURS

    config.load_user_config()

    observer = wgs84.latlon(
        config.OBSERVER_LAT, config.OBSERVER_LON, config.OBSERVER_ALT
    )

    t0 = ts.now()
    t1 = ts.from_datetime(t0.utc_datetime() + timedelta(hours=hours_ahead))

    all_passes = []

    for sat_name, sat_cfg in config.get_enabled_satellites().items():
        satellite, loaded_name = load_satellite(sat_name)
        if satellite is None:
            logger.warning(f"Could not load satellite: {sat_name}")
            continue

        try:
            t_events, events = satellite.find_events(observer, t0, t1, altitude_degrees=0.0)
        except Exception as e:
            logger.error(f"Pass prediction failed for {sat_name}: {e}")
            continue

        current_pass = {}
        for ti, event in zip(t_events, events):
            if event == 0:  # AOS
                current_pass = {
                    "aos": ti.utc_datetime().replace(tzinfo=timezone.utc),
                    "aos_azimuth": _compute_azimuth(satellite, observer, ti),
                }
            elif event == 1:  # Culmination
                if current_pass:
                    current_pass["max_elevation"] = _compute_elevation(satellite, observer, ti)
                    current_pass["culmination_time"] = ti.utc_datetime().replace(tzinfo=timezone.utc)
            elif event == 2:  # LOS
                if current_pass and "aos" in current_pass:
                    current_pass["los"] = ti.utc_datetime().replace(tzinfo=timezone.utc)
                    current_pass["los_azimuth"] = _compute_azimuth(satellite, observer, ti)
                    current_pass["duration_sec"] = int(
                        (current_pass["los"] - current_pass["aos"]).total_seconds()
                    )
                    current_pass["satellite"] = sat_name
                    current_pass["frequency"] = sat_cfg["frequency"]
                    current_pass["pipeline"] = sat_cfg["pipeline"]
                    current_pass["priority"] = sat_cfg["priority"]

                    max_elev = current_pass.get("max_elevation", 0)
                    if max_elev >= config.MIN_ELEVATION:
                        all_passes.append(current_pass)
                    current_pass = {}

    # Sort by AOS time
    all_passes.sort(key=lambda p: p["aos"])

    # Resolve conflicts
    resolved = resolve_conflicts(all_passes)

    logger.info(f"Predicted {len(all_passes)} passes ({len(resolved)} after conflict resolution)")
    for p in resolved[:10]:
        logger.info(
            f"  [{p['satellite']}] {p['aos'].strftime('%Y-%m-%d %H:%M')} → "
            f"{p['los'].strftime('%H:%M')} "
            f"(elev: {p.get('max_elevation', 0):.0f}°, "
            f"freq: {p['frequency'] / 1e6} MHz, "
            f"priority: {p['priority']})"
        )

    return resolved


def resolve_conflicts(passes: list) -> list:
    """
    Resolve overlapping passes by keeping the higher-priority satellite.
    If same priority, prefer higher elevation.
    """
    if len(passes) <= 1:
        return passes

    resolved = []
    skip_until = None

    for i, p in enumerate(passes):
        if skip_until and p["aos"] < skip_until:
            logger.info(
                f"  ⏭️ Skipped: {p['satellite']} {p['aos'].strftime('%H:%M')} "
                f"(conflict with higher priority)"
            )
            continue

        # Check for overlap with next pass
        conflicts = []
        for j in range(i + 1, len(passes)):
            next_p = passes[j]
            # Overlap if next AOS is before current LOS + buffer
            buffer = timedelta(seconds=config.AOS_BUFFER_SEC + config.LOS_BUFFER_SEC + 30)
            if next_p["aos"] < p["los"] + buffer:
                conflicts.append(next_p)
            else:
                break

        if not conflicts:
            resolved.append(p)
            skip_until = p["los"] + timedelta(seconds=config.LOS_BUFFER_SEC + 30)
        else:
            # Pick the best among current + conflicting passes
            all_candidates = [p] + conflicts
            # Sort: lower priority number first, then higher elevation
            all_candidates.sort(key=lambda x: (x["priority"], -x.get("max_elevation", 0)))
            winner = all_candidates[0]
            resolved.append(winner)
            skip_until = winner["los"] + timedelta(seconds=config.LOS_BUFFER_SEC + 30)

            for loser in all_candidates[1:]:
                if loser != winner:
                    logger.info(
                        f"  ⏭️ Conflict: {loser['satellite']} {loser['aos'].strftime('%H:%M')} "
                        f"skipped for {winner['satellite']} (priority {winner['priority']} > {loser['priority']})"
                    )

    return resolved


def _compute_elevation(satellite, observer, t):
    diff = satellite - observer
    topocentric = diff.at(t)
    alt, _, _ = topocentric.altaz()
    return alt.degrees


def _compute_azimuth(satellite, observer, t):
    diff = satellite - observer
    topocentric = diff.at(t)
    _, az, _ = topocentric.altaz()
    return az.degrees


# =============================================================================
# Recording Trigger
# =============================================================================
def run_recording(pass_info: dict) -> bool:
    """Trigger record.py for a given pass."""
    pass_json = json.dumps(pass_info, default=str)

    logger.info(f"Starting recording: {pass_info['satellite']} @ {pass_info.get('frequency', 0) / 1e6} MHz")
    update_state({
        "status": "recording",
        "current_pass": pass_info,
        "message": f"Recording {pass_info['satellite']}...",
    })

    try:
        # Timeout hesabı:
        # rtl_sdr capture: duration + AOS_BUFFER + LOS_BUFFER
        # Stabilizasyon bekleme: 60s
        # satdump decode (Pi 3B+): 10-20 dakika (30+ composite üretir)
        # Güvenlik marjı: 120s
        capture_time = pass_info["duration_sec"] + config.AOS_BUFFER_SEC + config.LOS_BUFFER_SEC
        decode_buffer = config.DECODE_TIMEOUT_SEC  # Pi 3B+ decode süresi (varsayılan 1200s)
        stabilization = 120  # 60s sleep + 60s güvenlik
        timeout = capture_time + stabilization + decode_buffer
        logger.info(f"  Timeout: {timeout}s (capture={capture_time}s + stab={stabilization}s + decode={decode_buffer}s)")

        result = subprocess.run(
            [sys.executable, str(config.BASE_DIR / "record.py"), pass_json],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0:
            logger.info("Recording completed successfully")
            return True
        else:
            logger.error(f"Recording failed (exit code {result.returncode})")
            if result.stdout:
                # Son 1000 karakter stdout (record.py console output)
                logger.error(f"  stdout (last 1000): {result.stdout[-1000:]}")
            if result.stderr:
                logger.error(f"  stderr: {result.stderr[-500:]}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(
            f"Recording process timed out after {timeout}s! "
            f"(capture={capture_time}s + decode_buffer={decode_buffer}s)"
        )
        return False
    except Exception as e:
        logger.error(f"Recording process error: {e}")
        return False


def run_cleanup():
    """Run cleanup.py to manage disk space."""
    try:
        subprocess.run(
            [sys.executable, str(config.BASE_DIR / "cleanup.py")],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        logger.error(f"Cleanup error: {e}")


# =============================================================================
# Sun Position (Skyfield)
# =============================================================================
def compute_sun_info() -> dict:
    """Compute sunrise, sunset, and daylight status for the observer location."""
    try:
        from skyfield import almanac

        observer = wgs84.latlon(
            config.OBSERVER_LAT, config.OBSERVER_LON, config.OBSERVER_ALT
        )

        eph = load('de421.bsp')

        now = ts.now()
        # Today's midnight and next midnight
        now_dt = now.utc_datetime()
        t0 = ts.utc(now_dt.year, now_dt.month, now_dt.day)
        t1 = ts.utc(now_dt.year, now_dt.month, now_dt.day + 1)

        # Find sunrise/sunset
        f = almanac.sunrise_sunset(eph, observer)
        times, events = almanac.find_discrete(t0, t1, f)

        sunrise = None
        sunset = None
        for ti, event in zip(times, events):
            if event:  # sunrise
                sunrise = ti.utc_datetime().isoformat()
            else:  # sunset
                sunset = ti.utc_datetime().isoformat()

        # Current daylight status
        is_daylight = bool(f(now))

        return {
            "sunrise": sunrise,
            "sunset": sunset,
            "is_daylight": is_daylight,
        }
    except Exception as e:
        logger.debug(f"Sun info hesaplanamadı: {e}")
        return {"sunrise": None, "sunset": None, "is_daylight": None}


# =============================================================================
# Main Scheduler Loop
# =============================================================================
def main():
    logger.info("=" * 60)
    logger.info("METEOR Autonomous Station — Scheduler v2.1")
    logger.info(f"  Observer: {config.OBSERVER_LAT}°N, {config.OBSERVER_LON}°E")
    logger.info(f"  Min elevation: {config.MIN_ELEVATION}°")
    logger.info(f"  Gain: {config.GAIN} dB | Bias-T: {'ON' if config.BIAS_TEE else 'OFF (kilitli)' if config.BIAS_TEE_LOCKED else 'OFF'}")
    logger.info("  Satellites:")
    for name, cfg in config.get_enabled_satellites().items():
        logger.info(f"    [{cfg['priority']}] {name} — {cfg['frequency'] / 1e6} MHz (NORAD {cfg['norad_id']})")
    logger.info("=" * 60)

    # --- Startup: Clear stale state ---
    update_state({
        "status": "starting",
        "message": "Scheduler başlatılıyor...",
        "next_pass": None,
        "upcoming_passes": [],
    })

    # --- Startup: Force TLE download ---
    logger.info("Startup: TLE güncelleniyor...")
    if download_tle():
        last_tle_update = time.time()
        logger.info("Startup: TLE güncellendi ✅")
    else:
        last_tle_update = time.time() - config.TLE_UPDATE_INTERVAL + 600
        logger.warning("Startup: TLE güncellenemedi, 10dk sonra tekrar denenecek")

    # Startup: State sıfırla (eski veriler kalmasın)
    update_state({
        "status": "starting",
        "message": "Sistem başlatılıyor...",
        "next_pass": None,
        "upcoming_passes": [],
    })

    while True:
        try:
            # --- Reload config (panelden yapılan değişiklikleri al) ---
            config.load_user_config()

            # --- TLE Update ---
            now = time.time()
            if now - last_tle_update > config.TLE_UPDATE_INTERVAL:
                if download_tle():
                    last_tle_update = now
                else:
                    last_tle_update = now - config.TLE_UPDATE_INTERVAL + 1800

            # --- Predict Passes (all satellites) ---
            passes = predict_passes()

            # --- Sun info ---
            sun_info = compute_sun_info()

            if not passes:
                logger.info("No upcoming passes. Sleeping 30 minutes...")
                update_state({
                    "status": "idle",
                    "message": "No upcoming passes",
                    "next_pass": None,
                    "upcoming_passes": [],
                    "sun": sun_info,
                    "passes_predicted_at": datetime.now(timezone.utc).isoformat(),
                })
                time.sleep(1800)
                continue

            next_pass = passes[0]
            now_utc = datetime.now(timezone.utc)
            wait_seconds = (next_pass["aos"] - now_utc).total_seconds() - config.AOS_BUFFER_SEC - 10  # 10s erken başlat

            # --- Geçmiş pass kontrolü: LOS geçmişse veya AOS 2+ dk geçmişse atla ---
            los_passed = next_pass["los"] < now_utc
            aos_too_old = (now_utc - next_pass["aos"]).total_seconds() > 120  # 2 dakikadan eski

            if los_passed or aos_too_old:
                reason = "LOS geçti" if los_passed else "AOS 2+ dk geçti"
                logger.warning(
                    f"Geçmiş pass atlanıyor: [{next_pass['satellite']}] "
                    f"{next_pass['aos'].strftime('%H:%M')}→{next_pass['los'].strftime('%H:%M')} "
                    f"({reason})"
                )
                time.sleep(5)
                continue

            # Serialize upcoming passes
            upcoming_serialized = []
            for p in passes[:15]:
                upcoming_serialized.append({
                    "aos": p["aos"].isoformat(),
                    "los": p["los"].isoformat(),
                    "max_elevation": round(p.get("max_elevation", 0), 1),
                    "duration_sec": p["duration_sec"],
                    "satellite": p.get("satellite", ""),
                    "frequency_mhz": p.get("frequency", 0) / 1e6,
                    "priority": p.get("priority", 99),
                })

            if wait_seconds > 0:
                logger.info(
                    f"Next: [{next_pass['satellite']}] "
                    f"{next_pass['aos'].strftime('%Y-%m-%d %H:%M UTC')} "
                    f"(in {wait_seconds:.0f}s)"
                )
                update_state({
                    "status": "waiting",
                    "message": f"Next: {next_pass['satellite']} in {int(wait_seconds // 60)}min",
                    "next_pass": upcoming_serialized[0] if upcoming_serialized else None,
                    "upcoming_passes": upcoming_serialized,
                    "sun": sun_info,
                    "passes_predicted_at": datetime.now(timezone.utc).isoformat(),
                })

                sleep_end = time.time() + wait_seconds
                while time.time() < sleep_end:
                    remaining = sleep_end - time.time()
                    if remaining <= 0:
                        break
                    chunk = min(60, remaining)
                    time.sleep(chunk)
                    remaining = sleep_end - time.time()

                    # Her dakika config'i yeniden yükle (panelden değişiklik kontrolü)
                    config.load_user_config()

                    update_state({
                        "status": "waiting",
                        "message": f"Next: {next_pass['satellite']} in {int(remaining // 60)}m {int(remaining % 60)}s",
                        "next_pass": upcoming_serialized[0] if upcoming_serialized else None,
                        "upcoming_passes": upcoming_serialized,
                        "sun": sun_info,
                    })

            # --- Kayıt öncesi config'i son kez yükle (güncel gain vb.) ---
            config.load_user_config()
            logger.info(f"Recording config: Gain={config.GAIN}dB, Bias-T={'ON' if config.BIAS_TEE else 'OFF'}")

            # --- Record ---
            success = run_recording(next_pass)

            # --- Post-Recording ---
            status_msg = f"{next_pass['satellite']}: {'✅ SUCCESS' if success else '❌ FAILED'}"
            logger.info(status_msg)

            run_cleanup()

            update_state({
                "status": "idle",
                "message": status_msg,
                "last_recording": {
                    "time": next_pass["aos"].isoformat(),
                    "satellite": next_pass["satellite"],
                    "success": success,
                    "max_elevation": round(next_pass.get("max_elevation", 0), 1),
                },
                "sun": sun_info,
            })

            time.sleep(10)

        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            update_state({"status": "stopped", "message": "Stopped by user"})
            break
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)
            update_state({"status": "error", "message": str(e)})
            time.sleep(60)


if __name__ == "__main__":
    main()
