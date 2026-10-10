"""Build the SQL aggregate views and export them as CSV for BI tools / reviewers."""
from __future__ import annotations

import csv
import logging
import sqlite3
from pathlib import Path

from .db import SQL_DIR, run_sql_file

log = logging.getLogger(__name__)

EXPORT_VIEWS = ["daily_sentiment_by_product", "rolling_7d_negative_share", "topic_sentiment_summary",
                "product_summary", "low_confidence_queue", "failed_predictions",
                "rating_sentiment_disagreement"]


def build_aggregates(conn: sqlite3.Connection) -> None:
    run_sql_file(conn, SQL_DIR / "03_aggregates.sql")
    conn.commit()


def export_aggregates(conn: sqlite3.Connection, out_dir) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for view in EXPORT_VIEWS + ["drift_alerts"]:
        cur = conn.execute(f"SELECT * FROM {view}")
        path = out_dir / f"{view}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([d[0] for d in cur.description])
            w.writerows(cur.fetchall())
        written.append(path)
    log.info("exported %d CSV files to %s", len(written), out_dir)
    return written
