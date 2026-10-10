"""Optional local transformer backend (Hugging Face). Enable with SENTIMENT_BACKEND=hf.

Imports are lazy so the rest of the project works without torch/transformers installed.
Any failure (missing library, model download error, runtime crash) is converted to ModelError,
which the enrichment step handles via retry -> fallback.
"""
from __future__ import annotations

from typing import Sequence

from .base import ModelError, Prediction, SentimentModel


class HFSentimentModel(SentimentModel):
    name = "hf-transformers"

    def __init__(self, model_name: str = "distilbert-base-uncased-finetuned-sst-2-english"):
        self.version = model_name
        self._model_name = model_name
        self._pipe = None

    def _load(self):
        if self._pipe is None:
            try:
                from transformers import pipeline  # noqa: WPS433 (lazy import on purpose)
                self._pipe = pipeline("sentiment-analysis", model=self._model_name)
            except Exception as exc:  # ImportError, OSError (download), ...
                raise ModelError(f"cannot load HF model '{self._model_name}': {exc}") from exc
        return self._pipe

    def predict(self, texts: Sequence[str]) -> list[Prediction]:
        pipe = self._load()
        try:
            outputs = pipe(list(texts), truncation=True, max_length=512)
        except Exception as exc:
            raise ModelError(f"HF inference failed: {exc}") from exc
        # SST-2 is binary (POSITIVE/NEGATIVE): ambiguous text shows up as a LOW SCORE,
        # which the confidence threshold in enrich.py routes to the review queue.
        return [Prediction(o["label"].lower(), float(o["score"])) for o in outputs]
