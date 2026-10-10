"""SQLite helpers: connection, schema creation and a small .sql file runner."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import ROOT

SQL_DIR = ROOT / "sql"


def connect(db_path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_sql_file(conn: sqlite3.Connection, path, params: dict | None = None) -> None:
    """Execute every statement in a .sql file *inside the caller's transaction*.

    (sqlite3.executescript() would silently COMMIT first, which breaks atomicity.)
    """
    buf = ""
    for line in Path(path).read_text().splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            stmt, buf = buf.strip(), ""
            if stmt:
                conn.execute(stmt, params or {})


def init_schema(conn: sqlite3.Connection) -> None:
    run_sql_file(conn, SQL_DIR / "01_create_tables.sql")
    conn.commit()
