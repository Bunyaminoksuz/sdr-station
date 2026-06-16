#!/usr/bin/env python3
"""
METEOR Autonomous Station — DB Migration Tool
Scans the passes/ directory and populates the SQLite database.
"""

import sys
import config
import database

def main():
    logger = config.get_logger("meteor-migrate")
    logger.info("Starting database migration from passes directory...")
    
    if not config.PASSES_DIR.exists():
        logger.warning(f"Passes directory not found: {config.PASSES_DIR}")
        sys.exit(0)
        
    pass_dirs = [d for d in config.PASSES_DIR.iterdir() if d.is_dir()]
    total = len(pass_dirs)
    logger.info(f"Found {total} pass directories to migrate.")
    
    for i, d in enumerate(pass_dirs):
        logger.info(f"[{i+1}/{total}] Syncing {d.name}...")
        database.sync_pass_directory(d)
        
    logger.info("Migration complete!")

if __name__ == "__main__":
    main()
