"""SQLite access (D23, D28): stdlib sqlite3, explicit SQL, explicit transactions, numbered migrations.

Every connection sets journal_mode=DELETE, synchronous=FULL, foreign_keys=ON, busy_timeout=5000 and
uses isolation_level=None (driver autocommit) so that transaction boundaries are explicit:

* ``Database.write()``  -> ``BEGIN IMMEDIATE`` ... ``COMMIT`` (every money or state mutation)
* ``Database.read()``   -> ``BEGIN`` ... ``COMMIT`` (snapshot reads: one consistent view)

WAL is deliberately not used (sqlite.org WAL-reset bug affects the deployed 3.45.1/3.46.1).
A connection is opened per transaction and closed afterwards, so no connection is shared between
threads. SQLite itself is the single-writer boundary; Python locks are never the financial guard.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterator

log = logging.getLogger("fazetime.db")

REQUIRED_PRAGMAS = {
    "journal_mode": "delete",
    "synchronous": 2,  # FULL
    "foreign_keys": 1,
    "busy_timeout": 5000,
}

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class PragmaError(RuntimeError):
    pass


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
    try:
        conn.row_factory = sqlite3.Row
        mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        actual = {
            "journal_mode": str(mode).lower(),
            "synchronous": conn.execute("PRAGMA synchronous").fetchone()[0],
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": conn.execute("PRAGMA busy_timeout").fetchone()[0],
        }
        if actual != REQUIRED_PRAGMAS:
            raise PragmaError(f"SQLite pragmas not applied: {actual}")
    except Exception:
        conn.close()
        raise
    return conn


@dataclass
class MigrationInfo:
    version: int
    name: str
    sha256: str


def _migration_files() -> list[tuple[int, str, str]]:
    pkg = resources.files("fazetime_api") / "migrations"
    found = []
    for entry in pkg.iterdir():
        m = _MIGRATION_NAME.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    versions = [v for v, _, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"migration numbering must be contiguous from 0001: {versions}")
    return found


def _split_sql(script: str) -> list[str]:
    """Split a migration into statements using SQLite's own completeness test (trigger-aware)."""
    statements, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            statements.append(buf.strip())
            buf = ""
    leftover = "\n".join(l for l in buf.splitlines() if l.strip() and not l.strip().startswith("--"))
    if leftover.strip():
        raise RuntimeError(f"incomplete SQL statement at end of migration: {leftover[:80]!r}")
    return statements


class Database:
    def __init__(self, path: str) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        return connect(self.path)

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """One BEGIN IMMEDIATE transaction. Commits on success, rolls back on any exception."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """One read transaction so every SELECT sees the same committed state."""
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            try:
                yield conn
            finally:
                if conn.in_transaction:
                    conn.execute("COMMIT")
        finally:
            conn.close()

    def migrate(self) -> list[MigrationInfo]:
        """Apply pending numbered migrations, each atomically. Refuses edited applied migrations."""
        applied_now: list[MigrationInfo] = []
        conn = self.connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL,"
                " applied_at_utc TEXT NOT NULL) STRICT"
            )
            for version, name, sql in _migration_files():
                digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute(
                        "SELECT name, sha256 FROM schema_migrations WHERE version = ?", (version,)
                    ).fetchone()
                    if row is not None:
                        conn.execute("COMMIT")
                        if row["sha256"] != digest:
                            raise RuntimeError(f"applied migration {name} was modified on disk; refusing to start")
                        continue
                    for statement in _split_sql(sql):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, sha256, applied_at_utc)"
                        " VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                        (version, name, digest),
                    )
                    conn.execute("COMMIT")
                    applied_now.append(MigrationInfo(version, name, digest))
                    log.info("applied migration %s", name)
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
            fk_problems = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_problems:
                raise RuntimeError(f"foreign key check failed: {len(fk_problems)} rows")
        finally:
            conn.close()
        return applied_now

    def schema_versions(self) -> list[dict]:
        with self.read() as conn:
            return [dict(r) for r in conn.execute("SELECT version, name, sha256 FROM schema_migrations ORDER BY version")]

    def backup(self, dest_path: str) -> None:
        """Consistent online copy via sqlite3.Connection.backup (§9.11)."""
        src = self.connect()
        try:
            dst = sqlite3.connect(dest_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()


def sqlite_version() -> str:
    return sqlite3.sqlite_version
