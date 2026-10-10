"""CLEAN -> CURATED: score reviews with the AI model and store label + confidence + topic.

What goes to the model : cleaned review text, truncated to MAX_CHARS (~512 tokens).
What comes back        : label in {positive, negative, neutral} and a confidence in [0, 1].
Handling of bad outcomes:
  * unsupported input (empty / too short / non-English script)   -> status 'failed' (model never called)
  * model raises / times out                                    -> retry once, then rule-based fallback
  * fallback also fails                                         -> status 'failed', reason 'model_unavailable'
  * malformed output (bad label, score outside [0,1], NaN)      -> status 'failed', reason 'invalid_model_output'
  * confidence below threshold                                  -> status 'low_confidence', label 'uncertain'
                                                                   (kept in raw_label), routed to low_confidence_queue
Only reviews WITHOUT a prediction are processed, so re-runs are incremental and idempotent.
"""
from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime

from .ai.base import LABELS, ModelError, SentimentModel
from .ai.topics import classify_topic

log = logging.getLogger(__name__)

MAX_CHARS = 2000
MIN_CHARS = 3


class ModelUnavailable(RuntimeError):
    """Primary (after retry) and fallback both failed."""


def validate_input(text: str) -> str | None:
    """Return a failure reason if the text cannot be scored, else None."""
    if not text or len(text.strip()) < MIN_CHARS:
        return "unsupported_input:too_short"
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "unsupported_input:no_letters"
    ascii_share = sum(1 for c in letters if c.isascii()) / len(letters)
    if ascii_share < 0.8:
        return "unsupported_input:non_english_script"
    return None


def _checked(preds, n: int):
    if preds is None or len(preds) != n:
        raise ModelError(f"model returned {0 if preds is None else len(preds)} predictions for {n} inputs")
    return preds


def call_with_resilience(primary: SentimentModel, fallback: SentimentModel, texts, retries: int = 1):
    """Try primary (1 + retries attempts), then fallback. Returns (predictions, model_used)."""
    for attempt in range(retries + 1):
        try:
            return _checked(primary.predict(texts), len(texts)), primary
        except Exception as exc:  # any backend failure, not only ModelError
            log.warning("primary model '%s' failed (attempt %d/%d): %s",
                        primary.name, attempt + 1, retries + 1, exc)
    try:
        log.warning("falling back to '%s'", fallback.name)
        return _checked(fallback.predict(texts), len(texts)), fallback
    except Exception as exc:
        raise ModelUnavailable(str(exc)) from exc


def _valid_prediction(p) -> bool:
    return (getattr(p, "label", None) in LABELS
            and isinstance(getattr(p, "score", None), (int, float))
            and not math.isnan(p.score) and 0.0 <= p.score <= 1.0)


def enrich_pending(conn: sqlite3.Connection, primary: SentimentModel, fallback: SentimentModel,
                   threshold: float = 0.65, batch_size: int = 64) -> dict:
    rows = conn.execute("""SELECT c.review_id, c.review_text FROM clean_reviews c
                           LEFT JOIN review_predictions p ON p.review_id = c.review_id
                           WHERE p.review_id IS NULL ORDER BY c.review_id""").fetchall()
    stats = {"processed": 0, "ok": 0, "low_confidence": 0, "failed": 0, "fallback_batches": 0}
    now = datetime.now().isoformat(timespec="seconds")

    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        out, scorable = [], []
        for r in chunk:
            reason = validate_input(r["review_text"])
            if reason:
                out.append((r["review_id"], None, None, None, None, None, None, None, "failed", reason, now))
            else:
                scorable.append(r)

        if scorable:
            texts = [r["review_text"][:MAX_CHARS] for r in scorable]
            try:
                preds, used = call_with_resilience(primary, fallback, texts)
                if used is not primary:
                    stats["fallback_batches"] += 1
                name, version = used.name, used.version
            except ModelUnavailable as exc:
                preds, name, version = None, None, None
                log.error("no model available for batch starting at %d: %s", start, exc)

            for i, r in enumerate(scorable):
                topic, topic_score = classify_topic(r["review_text"])
                if preds is None:
                    out.append((r["review_id"], None, None, None, topic, topic_score, None, None,
                                "failed", "model_unavailable", now))
                    continue
                p = preds[i]
                if not _valid_prediction(p):
                    out.append((r["review_id"], None, None, None, topic, topic_score, name, version,
                                "failed", "invalid_model_output", now))
                elif p.score < threshold:
                    out.append((r["review_id"], "uncertain", p.label, float(p.score), topic, topic_score,
                                name, version, "low_confidence", f"score<{threshold}", now))
                else:
                    out.append((r["review_id"], p.label, p.label, float(p.score), topic, topic_score,
                                name, version, "ok", None, now))

        conn.executemany(
            "INSERT OR REPLACE INTO review_predictions (review_id, sentiment_label, raw_label, "
            "sentiment_score, topic, topic_score, model_name, model_version, status, reason, processed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)", out)
        conn.commit()
        for o in out:
            stats["processed"] += 1
            stats[o[8]] += 1

    log.info("enriched %(processed)d reviews: ok=%(ok)d low_confidence=%(low_confidence)d "
             "failed=%(failed)d fallback_batches=%(fallback_batches)d", stats)
    return stats
