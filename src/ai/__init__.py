from .base import ModelError, Prediction, SentimentModel, LABELS
from .rule_model import RuleSentimentModel
from .hf_model import HFSentimentModel


def build_models(backend: str, hf_model_name: str = ""):
    """Return (primary, fallback). The fallback is always the dependency-free rule model."""
    fallback = RuleSentimentModel()
    if backend == "hf":
        return HFSentimentModel(hf_model_name), fallback
    if backend == "rule":
        return RuleSentimentModel(), fallback
    raise ValueError(f"Unknown SENTIMENT_BACKEND '{backend}' (use 'rule' or 'hf')")


__all__ = ["ModelError", "Prediction", "SentimentModel", "LABELS",
           "RuleSentimentModel", "HFSentimentModel", "build_models"]
