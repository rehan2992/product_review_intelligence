"""The ONLY contract the pipeline knows about. Any backend (local, API, fake) implements this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

LABELS = ("positive", "negative", "neutral")


class ModelError(RuntimeError):
    """Raised by a backend when it cannot produce predictions (timeout, missing lib, crash...)."""


@dataclass(frozen=True)
class Prediction:
    label: str    # one of LABELS
    score: float  # confidence in [0, 1]


class SentimentModel(ABC):
    name: str = "base"
    version: str = "0"

    @abstractmethod
    def predict(self, texts: Sequence[str]) -> list[Prediction]:
        """Return exactly one Prediction per input text, in order. Raise ModelError on failure."""
