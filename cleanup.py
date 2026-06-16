#!/usr/bin/env python3
"""
METEOR Autonomous Station — Disk Cleanup
Manages disk space by removing old passes and intermediate files.
"""

import json
import shutil
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
import database

# =============================================================================
# Logging
# =============================================================================
logger = config.get_logger("meteor-cleanup")


# =============================================================================
# Cleanup Functions
# =============================================================================
def get_disk_usage() -> dict:
    """Get disk usage information."""
    usage = shutil.disk_usage(str(config.PASSES_DIR))
    return {
        "total_gb": usage.total / (1024 ** 3),
        "used_gb": usage.used / (1024 ** 3),
        "free_gb": usage.free / (1024 ** 3),
        "percent_used": (usage.used / usage.total) * 100,
    }


def get_pass_directories() -> list:
    """Get all pass directories sorted by modification time (oldest first)."""
    if not config.PASSES_DIR.exists():
        return []

    passes = []
    for d in config.PASSES_DIR.iterdir():
        if d.is_dir():
            # Estimate directory size without deep rglob for speed
            # Since emergency cleanup uses size, we only really need it for that.
            # To avoid huge rglob on every pass, we can just get size from DB if needed,
            # but for cleanup, rough size is fine, or we can just rglob.
            dir_size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())

            passes.append({
                "path": d,
                "name": d.name,
                "size_mb": dir_size / (1024 ** 2),
                "mtime": d.stat().st_mtime,
            })

    # Sort by modification time (oldest first)
    passes.sort(key=lambda x: x["mtime"])
    return passes


def cleanup_old_passes():
    """Delete passes older than AUTO_DELETE_DAYS."""
    config.load_user_config()
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.AUTO_DELETE_DAYS)
    cutoff_ts = cutoff.timestamp()

    passes = get_pass_directories()
    deleted = 0

    for p in passes:
        if p["mtime"] < cutoff_ts:
            logger.info(
                f"Deleting old pass: {p['name']} "
                f"({p['size_mb']:.1f} MB, age > {config.AUTO_DELETE_DAYS} days)"
            )
            try:
                shutil.rmtree(p["path"])
                database.delete_pass(p["name"])
                deleted += 1
            except Exception as e:
                logger.error(f"Failed to delete {p['name']}: {e}")

    if deleted > 0:
        logger.info(f"Cleaned up {deleted} old pass(es)")


def emergency_cleanup():
    """Delete oldest passes if disk usage exceeds threshold."""
    disk = get_disk_usage()

    if disk["percent_used"] < config.EMERGENCY_CLEANUP_PERCENT:
        return

    logger.warning(
        f"⚠️ Disk usage critical: {disk['percent_used']:.1f}% "
        f"(threshold: {config.EMERGENCY_CLEANUP_PERCENT}%)"
    )

    passes = get_pass_directories()

    for p in passes:
        disk = get_disk_usage()
        if disk["percent_used"] < config.EMERGENCY_CLEANUP_PERCENT - 10:
            logger.info("Emergency cleanup complete, disk usage normalized")
            break

        logger.info(
            f"Emergency delete: {p['name']} ({p['size_mb']:.1f} MB)"
        )
        try:
            shutil.rmtree(p["path"])
            database.delete_pass(p["name"])
        except Exception as e:
            logger.error(f"Failed to delete {p['name']}: {e}")


def cleanup_intermediate_files():
    """Remove any leftover intermediate files across all passes.
    NOTE: .raw is NOT included — baseband.raw files are managed separately."""
    intermediate_extensions = {".cadu", ".frm", ".soft", ".bin", ".s", ".dat"}
    removed_total = 0

    for f in config.PASSES_DIR.rglob("*"):
        if f.is_file() and f.suffix.lower() in intermediate_extensions:
            size = f.stat().st_size
            try:
                f.unlink()
                removed_total += size
                logger.debug(f"Cleaned intermediate: {f}")
            except Exception as e:
                logger.warning(f"Failed to clean {f}: {e}")

    if removed_total > 0:
        logger.info(
            f"Cleaned {removed_total / 1024 / 1024:.1f} MB of intermediate files"
        )


def cleanup_old_basebands():
    """Delete baseband .raw files older than BASEBAND_DELETE_DAYS.
    Supports both legacy 'baseband.raw' and new '{timestamp}_baseband.raw' naming.
    Images and metadata are kept — only the large IQ file is removed."""
    if not hasattr(config, 'BASEBAND_DELETE_DAYS'):
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=config.BASEBAND_DELETE_DAYS)
    cutoff_ts = cutoff.timestamp()
    removed_total = 0

    for d in config.PASSES_DIR.iterdir():
        if not d.is_dir():
            continue

        # Find all baseband files: both 'baseband.raw' and '*_baseband.raw'
        raw_files = list(d.glob("*baseband.raw"))
        if not raw_files:
            continue

        for raw_file in raw_files:
            if raw_file.stat().st_mtime < cutoff_ts:
                size = raw_file.stat().st_size
                try:
                    raw_file.unlink()
                    removed_total += size

                    logger.info(
                        f"Baseband silindi: {d.name}/{raw_file.name} ({size / 1024 / 1024:.1f} MB, "
                        f">{config.BASEBAND_DELETE_DAYS} gün)"
                    )
                except Exception as e:
                    logger.warning(f"Baseband silinemedi {d.name}/{raw_file.name}: {e}")

        # Update metadata if any baseband was removed and no more remain
        remaining_raw = list(d.glob("*baseband.raw"))
        if not remaining_raw:
            meta_file = d / "metadata.json"
            if meta_file.exists():
                try:
                    with open(meta_file, "r") as f:
                        meta = json.load(f)
                    meta["has_baseband"] = False
                    meta["baseband_file"] = None
                    meta["baseband_size_mb"] = 0
                    with open(meta_file, "w") as f:
                        json.dump(meta, f, indent=2)
                    database.sync_pass_directory(d)
                except Exception as e:
                    logger.debug(f"Failed to update metadata for {d.name}: {e}")

    if removed_total > 0:
        logger.info(f"Toplam {removed_total / 1024 / 1024:.1f} MB baseband temizlendi")


# =============================================================================
# Main
# =============================================================================
def main():
    logger.info("Running disk cleanup...")

    disk_before = get_disk_usage()
    logger.info(
        f"Disk before: {disk_before['used_gb']:.1f} / {disk_before['total_gb']:.1f} GB "
        f"({disk_before['percent_used']:.1f}% used, {disk_before['free_gb']:.1f} GB free)"
    )

    # 1. Remove intermediate files
    cleanup_intermediate_files()

    # 2. Remove old passes
    cleanup_old_passes()

    # 3. Emergency cleanup if needed
    emergency_cleanup()

    # 4. Remove old baseband files (separate retention period)
    cleanup_old_basebands()

    disk_after = get_disk_usage()
    freed = disk_before["used_gb"] - disk_after["used_gb"]
    if freed > 0.001:
        logger.info(f"Freed {freed:.2f} GB of disk space")

    logger.info(
        f"Disk after: {disk_after['used_gb']:.1f} / {disk_after['total_gb']:.1f} GB "
        f"({disk_after['percent_used']:.1f}% used, {disk_after['free_gb']:.1f} GB free)"
    )

    # 5. SQLite WAL Checkpoint (Passive)
    try:
        with database.get_db() as conn:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        logger.debug("Executed SQLite WAL checkpoint (PASSIVE)")
    except Exception as e:
        logger.debug(f"WAL checkpoint failed: {e}")

if __name__ == "__main__":
    main()
