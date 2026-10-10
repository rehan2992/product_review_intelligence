"""RAW -> CLEAN. Python validates/normalises each row; SQL (sql/02_clean_reviews.sql) dedupes + upserts.

Rejection reasons written to rejected_reviews (nothing is silently dropped):
  missing_review_id | missing_product_id | empty_text | invalid_rating | invalid_date | future_date
  duplicate_review_id | near_duplicate        (the last two come from the SQL step)
Ratings that are missing are kept as NULL (the text can still be scored); ratings that are
present but invalid (0, 7, 'abc') reject the row because the data source is clearly unreliable.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
import sqlite3
from datetime import date, datetime

from .db import SQL_DIR, run_sql_file

log = logging.getLogger(__name__)

WORD_RATINGS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%b %d, %Y", "%d-%b-%Y")  # d/m/Y is day-first
NULL_TOKENS = {"", "null", "none", "nan", "n/a", "na"}
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean_text(value) -> str:
    text = _TAG.sub(" ", html.unescape(value or ""))
    return _SPACE.sub(" ", text).strip()


def text_fingerprint(text: str) -> str:
    normalised = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()


def parse_rating(value):
    """Return (rating | None, error | None)."""
    if value is None or str(value).strip().lower() in NULL_TOKENS:
        return None, None
    s = str(value).strip().lower()
    if s in WORD_RATINGS:
        return WORD_RATINGS[s], None
    try:
        f = float(s)
    except ValueError:
        return None, "invalid_rating"
    if f != int(f) or not 1 <= int(f) <= 5:
        return None, "invalid_rating"
    return int(f), None


def parse_date(value) -> date | None:
    s = (value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def validate_row(raw: dict, today: date | None = None):
    """Return (clean_row_dict, None) or (None, reject_reason)."""
    today = today or date.today()
    review_id = (raw.get("review_id") or "").strip()
    if not review_id:
        return None, "missing_review_id"
    product_id = (raw.get("product_id") or "").strip().upper()
    if not product_id:
        return None, "missing_product_id"
    text = clean_text(raw.get("review_text"))
    if not text:
        return None, "empty_text"
    rating, err = parse_rating(raw.get("rating"))
    if err:
        return None, err
    d = parse_date(raw.get("review_date"))
    if d is None:
        return None, "invalid_date"
    if d > today:
        return None, "future_date"
    return {
        "review_id": review_id,
        "product_id": product_id,
        "user_id": (raw.get("user_id") or "").strip() or None,
        "rating": rating,
        "review_text": text,
        "review_date": d.isoformat(),
        "text_hash": text_fingerprint(text),
    }, None


def clean_pending(conn: sqlite3.Connection, today: date | None = None) -> dict:
    """Process every raw row that has not been cleaned yet. Safe to call repeatedly."""
    pending = conn.execute("SELECT * FROM raw_reviews WHERE cleaned_at IS NULL ORDER BY raw_id").fetchall()
    if not pending:
        return {"raw_processed": 0, "clean_added": 0, "rejected_added": 0, "clean_total": _count(conn, "clean_reviews")}

    clean_before = _count(conn, "clean_reviews")
    rej_before = _count(conn, "rejected_reviews")
    try:
        conn.execute("DROP TABLE IF EXISTS temp.stg_valid")
        conn.execute("""CREATE TEMP TABLE stg_valid (
            raw_id INTEGER, review_id TEXT, product_id TEXT, user_id TEXT, rating INTEGER,
            review_text TEXT, review_date TEXT, text_hash TEXT, source_file TEXT, batch_id TEXT)""")
        valid, rejects = [], []
        for r in pending:
            row, reason = validate_row(dict(r), today)
            if reason:
                rejects.append((r["raw_id"], r["review_id"], r["product_id"], r["user_id"], r["rating"],
                                r["review_text"], r["review_date"], r["source_file"], r["batch_id"], reason))
            else:
                valid.append((r["raw_id"], row["review_id"], row["product_id"], row["user_id"], row["rating"],
                              row["review_text"], row["review_date"], row["text_hash"],
                              r["source_file"], r["batch_id"]))
        conn.executemany("INSERT INTO stg_valid VALUES (?,?,?,?,?,?,?,?,?,?)", valid)
        conn.executemany(
            "INSERT INTO rejected_reviews (raw_id, review_id, product_id, user_id, rating, review_text, "
            "review_date, source_file, batch_id, reject_reason, rejected_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))", rejects)
        run_sql_file(conn, SQL_DIR / "02_clean_reviews.sql")
        conn.execute("UPDATE raw_reviews SET cleaned_at = datetime('now') WHERE cleaned_at IS NULL")
        conn.commit()               # one atomic transaction for the whole cleaning step
    except Exception:
        conn.rollback()
        raise

    stats = {"raw_processed": len(pending),
             "clean_added": _count(conn, "clean_reviews") - clean_before,
             "rejected_added": _count(conn, "rejected_reviews") - rej_before,
             "clean_total": _count(conn, "clean_reviews")}
    log.info("cleaned %(raw_processed)d raw rows -> +%(clean_added)d clean, +%(rejected_added)d rejected", stats)
    return stats


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
