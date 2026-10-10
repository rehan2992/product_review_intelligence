"""RAW layer loader: CSV -> raw_reviews, incremental and idempotent.

* Every file is hashed; a file that was already loaded (same name + same hash) is skipped.
* Schema problems (missing required columns) are logged in ingestion_log and raised as SchemaError;
  nothing from a bad file is written to raw_reviews.
* Values are stored exactly as received (TEXT). Cleaning happens in the next step.
"""
from __future__ import annotations

import csv
import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["review_id", "product_id", "user_id", "rating", "review_text", "review_date"]


class SchemaError(ValueError):
    """Input file does not have the expected columns."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_file(conn: sqlite3.Connection, path) -> dict:
    path = Path(path)
    digest = file_hash(path)
    prev = conn.execute("SELECT file_hash, status FROM ingestion_log WHERE source_file = ?",
                        (path.name,)).fetchone()
    if prev and prev["file_hash"] == digest and prev["status"] == "loaded":
        log.info("skip %s (already loaded)", path.name)
        return {"file": path.name, "status": "skipped", "rows": 0}

    batch_id = path.stem if not prev else f"{path.stem}@{digest[:8]}"
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            msg = f"missing required columns: {missing}"
            conn.execute("INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,?)",
                         (path.name, digest, batch_id, 0, "failed", msg, _now()))
            conn.commit()
            raise SchemaError(f"{path.name}: {msg}")
        loaded_at = _now()
        rows = [(r["review_id"], r["product_id"], r["user_id"], r["rating"], r["review_text"],
                 r["review_date"], path.name, batch_id, loaded_at) for r in reader]

    try:
        conn.executemany(
            "INSERT INTO raw_reviews (review_id, product_id, user_id, rating, review_text, "
            "review_date, source_file, batch_id, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.execute("INSERT OR REPLACE INTO ingestion_log VALUES (?,?,?,?,?,?,?)",
                     (path.name, digest, batch_id, len(rows), "loaded", None, loaded_at))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log.info("loaded %s: %d raw rows (batch %s)", path.name, len(rows), batch_id)
    return {"file": path.name, "status": "loaded", "rows": len(rows)}
