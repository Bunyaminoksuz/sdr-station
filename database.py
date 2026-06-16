import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
import config

logger = config.get_logger("meteor-db")

DB_FILE = config.BASE_DIR / "passes.db"

def get_db():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        with get_db() as conn:
            # Enable WAL mode for high concurrency
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS passes (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    satellite TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    images_json TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    total_size_mb REAL NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Migration: Add telemetry_json column if it doesn't exist
            cursor = conn.execute("PRAGMA table_info(passes)")
            columns = [col["name"] for col in cursor.fetchall()]
            if "telemetry_json" not in columns:
                conn.execute("ALTER TABLE passes ADD COLUMN telemetry_json TEXT DEFAULT '{}'")
                
            # İndeksler sorgu hızını artırır
            conn.execute('CREATE INDEX IF NOT EXISTS idx_date ON passes(date)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_satellite ON passes(satellite)')
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

def upsert_pass(pass_id: str, date: str, satellite: str, metadata: dict, images: list, files: list, total_size_mb: float, telemetry: dict = None):
    """Insert or update a pass in the database."""
    if telemetry is None:
        telemetry = {}
    try:
        with get_db() as conn:
            conn.execute('''
                INSERT INTO passes (id, date, satellite, metadata_json, images_json, files_json, total_size_mb, telemetry_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    metadata_json=excluded.metadata_json,
                    images_json=excluded.images_json,
                    files_json=excluded.files_json,
                    total_size_mb=excluded.total_size_mb,
                    telemetry_json=excluded.telemetry_json
            ''', (
                pass_id,
                date,
                satellite,
                json.dumps(metadata, default=str),
                json.dumps(images, default=str),
                json.dumps(files, default=str),
                total_size_mb,
                json.dumps(telemetry, default=str)
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to upsert pass {pass_id}: {e}")

def get_passes(satellite: str = None) -> list:
    """Get all passes, optionally filtered by satellite, sorted descending by date/id."""
    try:
        with get_db() as conn:
            query = 'SELECT * FROM passes'
            params = []
            if satellite:
                query += ' WHERE satellite = ?'
                params.append(satellite)
            query += ' ORDER BY date DESC, id DESC'
            
            cursor = conn.execute(query, params)
            passes = []
            for row in cursor.fetchall():
                passes.append({
                    "id": row["id"],
                    "date": row["date"],
                    "satellite": row["satellite"],
                    "metadata": json.loads(row["metadata_json"]),
                    "images": json.loads(row["images_json"]),
                    "files": json.loads(row["files_json"]),
                    "total_size_mb": row["total_size_mb"],
                    "telemetry": json.loads(row.get("telemetry_json", "{}")),
                    "created_at": row["created_at"]
                })
            return passes
    except Exception as e:
        logger.error(f"Failed to get passes: {e}")
        return []

def get_pass(pass_id: str) -> dict:
    """Get a single pass by ID."""
    try:
        with get_db() as conn:
            cursor = conn.execute('SELECT * FROM passes WHERE id = ?', (pass_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "date": row["date"],
                    "satellite": row["satellite"],
                    "metadata": json.loads(row["metadata_json"]),
                    "images": json.loads(row["images_json"]),
                    "files": json.loads(row["files_json"]),
                    "total_size_mb": row["total_size_mb"],
                    "telemetry": json.loads(row.get("telemetry_json", "{}")),
                    "created_at": row["created_at"]
                }
            return None
    except Exception as e:
        logger.error(f"Failed to get pass {pass_id}: {e}")
        return None

def delete_pass(pass_id: str):
    """Delete a pass from the database."""
    try:
        with get_db() as conn:
            conn.execute('DELETE FROM passes WHERE id = ?', (pass_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to delete pass {pass_id}: {e}")

def sync_pass_directory(pass_dir: Path):
    """Read a pass directory and upsert it into the DB. Used by migration and cleanup."""
    if not pass_dir.is_dir():
        return
        
    from utils import detect_satellite, extract_date, file_type, parse_telemetry
    
    try:
        metadata = detect_satellite(pass_dir)
        satellite = metadata.get("satellite", "Unknown")
        date = extract_date(pass_dir.name, metadata)
        
        # Telemetry okuma (varsa özetle)
        telemetry_summary = {}
        for tl_path in [pass_dir / "telemetry.json", pass_dir / "output" / "telemetry.json"]:
            if tl_path.exists():
                try:
                    with open(tl_path, "r") as f:
                        tl = json.load(f)
                    telemetry_summary = parse_telemetry(tl)
                except Exception as e:
                    logger.debug(f"telemetry.json read error in db sync: {e}")
                break
        
        images = []
        all_files = []
        total_size = 0
        
        for f in pass_dir.rglob("*"):
            if f.is_file():
                size = f.stat().st_size
                total_size += size
                rel = f.relative_to(pass_dir)
                file_info = {
                    "name": f.name,
                    "path": str(rel),
                    "size_kb": round(size / 1024, 1),
                    "type": file_type(f.suffix),
                }
                all_files.append(file_info)
                if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
                    images.append(file_info)
                    
        total_size_mb = round(total_size / (1024 ** 2), 1)
        upsert_pass(pass_dir.name, date, satellite, metadata, images, all_files, total_size_mb, telemetry_summary)
        
    except Exception as e:
        logger.error(f"Failed to sync pass directory {pass_dir.name}: {e}")

# Initialize db schema when imported
init_db()
