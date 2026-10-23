"""SQLite connection management and a minimal forward-only migration runner.

Migration files live in ``storage/migrations`` as ``NNNN_name.sql``. Applied versions are
recorded in ``schema_migrations`` (version, name, applied_at, checksum). A changed checksum
for an already-applied migration is an error: migrations are append-only.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from impactlens.timeutil import utc_now_iso


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def load_migrations() -> list[Migration]:
    migrations = []
    folder = resources.files("impactlens.storage") / "migrations"
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".sql"):
            continue
        prefix, _, rest = entry.name.partition("_")
        migrations.append(Migration(int(prefix), rest.removesuffix(".sql"), entry.read_text("utf-8")))
    versions = [m.version for m in migrations]
    if versions != sorted(set(versions)):
        raise MigrationError("migration versions must be unique and ordered")
    return migrations


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations; returns versions applied in this call."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
    )
    applied = {
        row["version"]: row["checksum"]
        for row in conn.execute("SELECT version, checksum FROM schema_migrations")
    }
    done: list[int] = []
    for migration in load_migrations():
        if migration.version in applied:
            if applied[migration.version] != migration.checksum:
                raise MigrationError(f"migration {migration.version} was modified after being applied")
            continue
        try:
            conn.execute("BEGIN")
            for statement in _split_sql(migration.sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, utc_now_iso(), migration.checksum),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(f"migration {migration.version} failed: {exc}") from exc
        done.append(migration.version)
    return done


def _split_sql(sql: str) -> list[str]:
    """Split a migration script into statements, keeping trigger bodies intact."""
    statements, buf = [], []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        candidate = "\n".join(buf)
        if stripped.endswith(";") and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            buf = []
    if buf:
        statements.append("\n".join(buf))
    return statements


def schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["v"] or 0)


def latest_known_version() -> int:
    migrations = load_migrations()
    return migrations[-1].version if migrations else 0


class Database:
    """Owns one SQLite connection; serializes writes with a process-local lock."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = connect(path)
        self._lock = threading.RLock()

    def initialize(self) -> list[int]:
        with self._lock:
            return migrate(self.conn)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, params))

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def close(self) -> None:
        self.conn.close()
