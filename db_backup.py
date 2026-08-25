"""Recurring sentinel.db backup -- open item since 2026-07-20 (two real data-loss
incidents, ~2 days of proposal/track-record history each time, because the only
existing copy was a manually-refreshed SSD mirror).

Uses sqlite3's online backup API (not a raw file copy) so a backup taken while
main.py's live process holds the DB open is still transactionally consistent.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from config import DB_PATH

SSD_BACKUP_DIR = Path("/Volumes/Iron 1TBSSD/Claude/FredAI/data/backups")
LOCAL_BACKUP_DIR = Path(DB_PATH).parent / "backups"
KEEP_LAST_N = 48  # hourly cadence -> 2 days, matches the SSD mirror's own historical staleness window


def _backup_dir() -> Path:
    if SSD_BACKUP_DIR.parent.parent.exists():
        return SSD_BACKUP_DIR
    return LOCAL_BACKUP_DIR


def backup_db() -> str | None:
    """Write a consistent snapshot of sentinel.db, prune old ones, return the new path (or None on failure)."""
    dest_dir = _backup_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[DBBackup] Could not create {dest_dir}: {e}")
        return None

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    dest_path = dest_dir / f"sentinel-{stamp}.db"

    try:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(str(dest_path))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    except sqlite3.Error as e:
        print(f"[DBBackup] Backup failed: {e}")
        return None

    _prune_old_backups(dest_dir)
    return str(dest_path)


def _prune_old_backups(dest_dir: Path):
    backups = sorted(dest_dir.glob("sentinel-*.db"))
    for stale in backups[:-KEEP_LAST_N]:
        try:
            stale.unlink()
        except OSError:
            pass
