"""End-to-end tests on generated data: the planted drift is detected, stable data raises nothing."""
import pytest

from src import db
from src.config import load_config
from src.generate_data import DRIFT_PRODUCT, generate
from src.pipeline import run


def _run(tmp_path, drift):
    data = tmp_path / ("drift" if drift else "stable")
    generate(data, drift=drift)
    cfg = load_config(db_path=tmp_path / f"{data.name}.db", data_dir=data, output_dir=tmp_path / f"out_{data.name}")
    return run(cfg), cfg


@pytest.fixture(scope="module")
def drifted(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("d"), True)


@pytest.fixture(scope="module")
def stable(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("s"), False)


def test_planted_spike_is_detected_only_for_the_right_product(drifted):
    summary, _ = drifted
    neg = [a for a in summary["alerts"] if a["metric"] == "negative_share"]
    assert [a["product_id"] for a in neg] == [DRIFT_PRODUCT]
    assert neg[0]["severity"] == "high" and neg[0]["current_value"] > 0.45
    assert {a["product_id"] for a in summary["alerts"]} == {DRIFT_PRODUCT}
    assert any(a["metric"] == "topic_share:battery" for a in summary["alerts"])


def test_stable_data_raises_no_false_alarm(stable):
    summary, _ = stable
    assert summary["alerts"] == []


def test_sample_pipeline_outputs_have_expected_schema_and_nothing_is_lost(drifted):
    summary, cfg = drifted
    conn = db.connect(cfg.db_path)
    cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
    assert {"review_id", "sentiment_label", "sentiment_score", "topic", "status", "model_name"} <= cols("review_predictions")
    assert {"product_id", "review_date", "negative_share", "avg_confidence"} <= cols("daily_sentiment_by_product")
    t = summary["totals"]
    assert t["clean_reviews"] == t["review_predictions"]
    assert t["rejected_reviews"] > 0 and t["raw_reviews"] > t["clean_reviews"]
    assert conn.execute("SELECT COUNT(*) FROM low_confidence_queue").fetchone()[0] > 0
    assert (cfg.output_dir / "drift_report.md").exists()


def test_rerunning_drift_check_does_not_duplicate_alerts(drifted):
    summary, cfg = drifted
    run(cfg)  # second run: everything already loaded
    conn = db.connect(cfg.db_path)
    assert conn.execute("SELECT COUNT(*) FROM drift_alerts").fetchone()[0] == len(summary["alerts"])
