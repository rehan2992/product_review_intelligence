"""Keyword-based topic classifier with a confidence score (share of keyword hits)."""
from __future__ import annotations

import re

TOPIC_KEYWORDS = {
    "delivery": ["delivery", "shipping", "shipped", "package", "packed", "arrived", "box",
                 "courier", "late", "packaging"],
    "quality":  ["quality", "build", "solid", "made", "broke", "broken", "stopped working",
                 "flimsy", "durable", "works", "premium", "cheap"],
    "price":    ["price", "expensive", "overpriced", "value", "money", "affordable", "worth",
                 "deal", "penny"],
    "support":  ["support", "service", "customer", "helpful", "rude", "replied", "refund",
                 "team", "unhelpful"],
    "battery":  ["battery", "charge", "charges", "charging", "drains", "firmware", "update"],
}
_PATTERNS = {t: [re.compile(rf"\b{re.escape(k)}\b") for k in kws] for t, kws in TOPIC_KEYWORDS.items()}


def classify_topic(text: str) -> tuple[str, float]:
    """Return (topic, score). score = top topic hits / all hits; ('other', 0.0) if nothing matched."""
    lowered = (text or "").lower()
    hits = {t: sum(1 for p in pats if p.search(lowered)) for t, pats in _PATTERNS.items()}
    total = sum(hits.values())
    if total == 0:
        return "other", 0.0
    topic = max(hits, key=lambda t: hits[t])
    return topic, round(hits[topic] / total, 3)
