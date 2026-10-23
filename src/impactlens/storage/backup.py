"""Consistent SQLite online backup and verified restore."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from impactlens.timeutil import utc_now


class BackupError(RuntimeError):
    pass


def integrity_check(path: str | Path) -> str:
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def backup_database(db_path: str | Path, backup_dir: str | Path, *, keep: int = 14) -> Path:
    """Online backup via the SQLite backup API (safe while the app is running)."""
    src_path = Path(db_path)
    if not src_path.is_file():
        raise BackupError(f"database not found: {src_path}")
    out_dir = Path(backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"impactlens-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.db"
    counter = 1
    while target.exists():
        target = out_dir / f"impactlens-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{counter}.db"
        counter += 1
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    result = integrity_check(target)
    if result != "ok":
        target.unlink(missing_ok=True)
        raise BackupError(f"backup failed integrity check: {result}")
    backups = sorted(out_dir.glob("impactlens-*.db"))
    for old in backups[: max(0, len(backups) - keep)]:
        old.unlink(missing_ok=True)
    return target


def restore_database(backup_path: str | Path, db_path: str | Path, *, force: bool = False) -> Path:
    """Verify a backup and restore it; an existing DB is preserved as ``*.pre-restore``."""
    backup = Path(backup_path)
    target = Path(db_path)
    if not backup.is_file():
        raise BackupError(f"backup not found: {backup}")
    result = integrity_check(backup)
    if result != "ok":
        raise BackupError(f"backup failed integrity check: {result}")
    if target.exists():
        if not force:
            raise BackupError(f"{target} exists; stop writers and pass force=True to replace it")
        preserved = target.with_suffix(target.suffix + f".pre-restore-{utc_now().strftime('%Y%m%dT%H%M%SZ')}")
        shutil.move(str(target), preserved)
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, target)
    if integrity_check(target) != "ok":
        raise BackupError("restored database failed integrity check")
    return target
