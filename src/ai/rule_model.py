"""Dependency-free, lexicon-based sentiment model (a small VADER-style scorer).

Used as (a) the default backend so the project runs from a clean setup with no downloads,
and (b) the fallback when a heavier model fails.

Confidence logic:
  * evidence = sum of positive / negative cue strengths (negation + intensifier aware)
  * margin   = (pos - neg) / (pos + neg)            in [-1, 1]
  * confidence = 0.5 + 0.5 * |margin| * min(1, evidence / 2)
  => mixed reviews (pos ~ neg) and reviews with no cues land near 0.5 (low confidence).
"""
from __future__ import annotations

import re
from typing import Sequence

from .base import ModelError, Prediction, SentimentModel

POSITIVE = """good great excellent amazing fantastic awesome love loved perfect perfectly happy
fast quick quickly early solid premium well friendly helpful resolved affordable worth best
nice smooth reliable impressed satisfied recommend wonderful superb pleased delighted durable
comfortable""".split()

NEGATIVE = """bad poor terrible awful horrible worst slow late damaged crushed broke broken useless
disappointed disappointing disappointment overpriced expensive waste unhelpful rude flimsy cheap
forever drains died defective faulty junk hate hated frustrating annoying laggy scam
unreliable""".split()

NEUTRAL = "okay ok average decent fine mediocre acceptable".split()

INTENSIFIERS = {"very", "really", "extremely", "super", "terribly", "badly", "totally",
                "completely", "incredibly", "so"}
NEGATIONS = {"not", "no", "never", "hardly", "without", "isnt", "wasnt", "dont", "didnt"}

_LEXICON = {**{w: 1 for w in POSITIVE}, **{w: -1 for w in NEGATIVE}, **{w: 0 for w in NEUTRAL}}
_TOKEN = re.compile(r"[a-z']+")


def _is_negation(tok: str) -> bool:
    return tok in NEGATIONS or tok.endswith("n't")


class RuleSentimentModel(SentimentModel):
    name = "rule-lexicon"
    version = "1.0"

    def predict(self, texts: Sequence[str]) -> list[Prediction]:
        if texts is None:
            raise ModelError("texts is None")
        return [self._score(t) for t in texts]

    def _score(self, text: str) -> Prediction:
        tokens = _TOKEN.findall((text or "").lower())
        pos = neg = 0.0
        neutral_hits = 0
        for i, tok in enumerate(tokens):
            polarity = _LEXICON.get(tok)
            if polarity is None:
                continue
            if polarity == 0:
                neutral_hits += 1
                continue
            context = tokens[max(0, i - 2):i]
            value = float(polarity)
            if any(c in INTENSIFIERS for c in context):
                value *= 1.5
            if any(_is_negation(c) for c in context):
                value = -value * 0.8
            if value > 0:
                pos += value
            else:
                neg += -value

        total = pos + neg
        if total == 0:
            return Prediction("neutral", 0.7 if neutral_hits else 0.5)
        margin = (pos - neg) / total
        label = "positive" if margin > 0.2 else "negative" if margin < -0.2 else "neutral"
        confidence = 0.5 + 0.5 * abs(margin) * min(1.0, total / 2.0)
        return Prediction(label, round(min(confidence, 0.99), 4))
