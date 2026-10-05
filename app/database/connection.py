"""SQLite connection management.

Connections are opened per operation (SQLite is fast to open, and this keeps the
application thread-safe without a connection pool).  WAL mode plus a busy timeout
means the API can serve reads while a background scan writes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..logging_config import get_logger
from .schema import MIGRATIONS, SCHEMA_VERSION, migration_statements

log = get_logger("database.connection")


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string with a trailing ``Z``."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DatabaseError(RuntimeError):
    """Raised when the database cannot be opened or migrated."""


class Database:
    """Owns the SQLite file and the schema."""

    def __init__(self, path: str | Path, *, timeout: float = 10.0) -> None:
        self.path = Path(path)
        self.timeout = timeout

    # ------------------------------------------------------------------ basics
    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=self.timeout)
        except (sqlite3.Error, OSError) as exc:
            raise DatabaseError(f"cannot open database {self.path}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error:  # pragma: no cover - some filesystems refuse WAL
            log.warning("WAL mode unavailable for %s, continuing in rollback journal mode", self.path)
        return conn

    @contextmanager
    def connection(self, conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
        """Yield a connection; commit on success, rollback on failure.

        Passing an existing connection reuses it (nested usage inside a
        :meth:`transaction` block) and leaves commit handling to the outermost owner.
        """
        if conn is not None:
            yield conn
            return
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            yield conn

    # ------------------------------------------------------------------ schema
    def current_version(self, conn: sqlite3.Connection | None = None) -> int:
        with self.connection(conn) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            row = connection.execute("SELECT MAX(version) AS version FROM schema_version").fetchone()
        return int(row["version"]) if row and row["version"] is not None else 0

    def migrate(self) -> int:
        """Apply pending migrations. Returns the resulting schema version."""
        version = self.current_version()
        if version > SCHEMA_VERSION:
            raise DatabaseError(
                f"database {self.path} was written by a newer version (schema v{version}, this build supports "
                f"v{SCHEMA_VERSION}). Upgrade the application or point GITDASH_DATABASE_PATH at another file."
            )
        for target, script in MIGRATIONS:
            if target <= version:
                continue
            log.info("applying database migration v%s", target)
            try:
                with self.transaction() as conn:
                    for statement in migration_statements(script):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
                        (target, utc_now()),
                    )
            except sqlite3.Error as exc:
                raise DatabaseError(f"migration v{target} failed: {exc}") from exc
            version = target
        return version

    # ------------------------------------------------------------------ upkeep
    def backup(self, destination: str | Path) -> Path:
        """Copy the database to ``destination`` using the SQLite backup API."""
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.connection() as source, sqlite3.connect(str(target)) as destination_conn:
                source.backup(destination_conn)
        except sqlite3.Error as exc:
            raise DatabaseError(f"backup failed: {exc}") from exc
        log.info("database backup written to %s", target)
        return target

    def size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                total += candidate.stat().st_size
        return total

    def vacuum(self) -> None:
        with self.connection() as conn:
            conn.execute("VACUUM")

    def reset(self) -> None:
        """Drop every dashboard table (used by tests and ``--reset`` CLI flag)."""
        with self.transaction() as conn:
            tables = [
                "file_changes",
                "contributors",
                "commits",
                "branches",
                "scan_runs",
                "repositories",
                "app_state",
                "schema_version",
            ]
            for table in tables:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
