import csv
from datetime import date, timedelta

import pytest

from src import db
from src.ai.base import ModelError, Prediction, SentimentModel
from src.ingest import REQUIRED_COLUMNS


class FakeModel(SentimentModel):
    """Deterministic stand-in: no downloads, fast, fully controllable."""
    name, version = "fake", "test"

    def __init__(self, label="positive", score=0.9, raises=None, bad_output=None):
        self.label, self.score, self.raises, self.bad_output = label, score, raises, bad_output
        self.calls = 0

    def predict(self, texts):
        self.calls += 1
        if self.raises:
            raise self.raises
        if self.bad_output == "short":
            return [Prediction(self.label, self.score)] * (len(texts) - 1)
        if self.bad_output == "garbage":
            return [Prediction("ecstatic", 7.5) for _ in texts]
        return [Prediction(self.label, self.score) for _ in texts]


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.init_schema(c)
    yield c
    c.close()


def write_csv(path, rows, columns=None):
    columns = columns or REQUIRED_COLUMNS
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({"user_id": "U1", "rating": "5", "product_id": "P01",
                        "review_date": (date.today() - timedelta(days=2)).isoformat(), **r})
    return path
