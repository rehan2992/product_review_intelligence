import pytest

from src.ai import RuleSentimentModel
from src.ai.base import ModelError
from src.ai.topics import classify_topic
from src.clean import clean_pending
from src.enrich import call_with_resilience, enrich_pending, validate_input
from src.ingest import ingest_file
from tests.conftest import FakeModel, write_csv


@pytest.fixture
def loaded(conn, tmp_path):
    p = write_csv(tmp_path / "b.csv", [{"review_id": f"r{i}", "review_text": f"Review text number {i}",
                                         "user_id": f"U{i}"} for i in range(4)])
    ingest_file(conn, p)
    clean_pending(conn)
    return conn


def status_counts(conn):
    return dict(conn.execute("SELECT status, COUNT(*) FROM review_predictions GROUP BY status").fetchall())


def test_low_confidence_is_routed_to_review_queue(loaded):
    enrich_pending(loaded, FakeModel("positive", 0.40), FakeModel(), threshold=0.65)
    assert status_counts(loaded) == {"low_confidence": 4}
    row = loaded.execute("SELECT sentiment_label, raw_label FROM review_predictions").fetchone()
    assert (row["sentiment_label"], row["raw_label"]) == ("uncertain", "positive")


def test_primary_failure_retries_then_falls_back_and_records_model(loaded):
    """FAILURE PATH: model crashes -> retried once -> rule fallback used and recorded."""
    primary = FakeModel(raises=ModelError("boom"))
    stats = enrich_pending(loaded, primary, FakeModel("negative", 0.9, ), threshold=0.65)
    assert primary.calls == 2                       # first attempt + one retry
    assert stats["fallback_batches"] == 1
    assert {r[0] for r in loaded.execute("SELECT model_name FROM review_predictions")} == {"fake"}
    assert status_counts(loaded) == {"ok": 4}


def test_both_models_down_marks_failed_without_crashing(loaded):
    enrich_pending(loaded, FakeModel(raises=TimeoutError("t")), FakeModel(raises=ModelError("x")))
    assert status_counts(loaded) == {"failed": 4}
    assert loaded.execute("SELECT DISTINCT reason FROM review_predictions").fetchone()[0] == "model_unavailable"


@pytest.mark.parametrize("bad", ["short", "garbage"])
def test_malformed_model_output_is_not_stored_as_truth(loaded, bad):
    enrich_pending(loaded, FakeModel(bad_output=bad), FakeModel(bad_output=bad))
    assert "ok" not in status_counts(loaded)
    assert set(status_counts(loaded)) == {"failed"}


def test_unsupported_input_never_reaches_model():
    assert validate_input("") == "unsupported_input:too_short"
    assert validate_input("बहुत अच्छा उत्पाद") == "unsupported_input:non_english_script"
    assert validate_input("12345 !!!") == "unsupported_input:no_letters"
    assert validate_input("Great product") is None


def test_rule_model_behaviour_and_topics():
    m = RuleSentimentModel()
    pos, neg, neg2, mixed = m.predict(["Great value, love it", "Terrible, broke in a week",
                                       "This is not good at all", "Great screen but terrible battery"])
    assert pos.label == "positive" and neg.label == "negative" and neg2.label == "negative"
    assert mixed.score < 0.65                       # mixed -> low confidence
    assert classify_topic("The battery drains and the firmware update is awful")[0] == "battery"
    assert classify_topic("zzz") == ("other", 0.0)
