"""Central configuration. Values come from environment variables or an optional .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Config:
    db_path: Path
    data_dir: Path
    output_dir: Path
    sentiment_backend: str = "rule"
    hf_model_name: str = "distilbert-base-uncased-finetuned-sst-2-english"
    confidence_threshold: float = 0.65
    batch_size: int = 64


def load_config(**overrides) -> Config:
    _load_dotenv(ROOT / ".env")

    def path(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else ROOT / p

    cfg = dict(
        db_path=path(os.getenv("DB_PATH", "data/reviews.db")),
        data_dir=path(os.getenv("DATA_DIR", "data/sample")),
        output_dir=path(os.getenv("OUTPUT_DIR", "output")),
        sentiment_backend=os.getenv("SENTIMENT_BACKEND", "rule"),
        hf_model_name=os.getenv("HF_MODEL_NAME", "distilbert-base-uncased-finetuned-sst-2-english"),
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.65")),
        batch_size=int(os.getenv("BATCH_SIZE", "64")),
    )
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    return Config(**cfg)
