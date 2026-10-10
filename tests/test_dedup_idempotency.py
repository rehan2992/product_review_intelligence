from src.clean import clean_pending
from src.ingest import SchemaError, ingest_file
from tests.conftest import FakeModel, write_csv
from src.enrich import enrich_pending
import pytest


def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("raw_reviews", "clean_reviews", "rejected_reviews", "review_predictions")}


def run_all(conn, path):
    ingest_file(conn, path)
    clean_pending(conn)
    enrich_pending(conn, FakeModel(), FakeModel())


def test_duplicate_review_ids_and_near_duplicates_collapse(conn, tmp_path):
    p = write_csv(tmp_path / "b.csv", [
        {"review_id": "r1", "review_text": "Great phone"},
        {"review_id": "r1", "review_text": "Great phone"},                     # exact re-delivery
        {"review_id": "r2", "review_text": "Great  phone!!", "user_id": "U1"},  # near-dup of r1 (same user/product/text)
        {"review_id": "r3", "review_text": "Great phone", "user_id": "U9"},     # same text, different user -> keep
    ])
    ingest_file(conn, p)
    clean_pending(conn)
    ids = sorted(r[0] for r in conn.execute("SELECT review_id FROM clean_reviews"))
    assert ids == ["r1", "r3"]
    why = sorted(r[0] for r in conn.execute("SELECT reject_reason FROM rejected_reviews"))
    assert why == ["duplicate_review_id", "near_duplicate"]


def test_pipeline_is_idempotent(conn, tmp_path):
    p = write_csv(tmp_path / "b.csv", [{"review_id": f"r{i}", "review_text": f"Product number {i} is great",
                                         "user_id": f"U{i}"} for i in range(20)])
    run_all(conn, p)
    first = counts(conn)
    run_all(conn, p)
    run_all(conn, p)
    assert counts(conn) == first
    assert first["clean_reviews"] == first["review_predictions"] == 20


def test_incremental_batch_with_overlap_and_edited_review(conn, tmp_path):
    b1 = write_csv(tmp_path / "b1.csv", [{"review_id": "r1", "review_text": "Good one", "user_id": "A"},
                                          {"review_id": "r2", "review_text": "Bad one", "user_id": "B"}])
    b2 = write_csv(tmp_path / "b2.csv", [{"review_id": "r2", "review_text": "Bad one", "user_id": "B"},       # re-delivered
                                          {"review_id": "r1", "review_text": "Good one, edited", "user_id": "A"},  # edited
                                          {"review_id": "r3", "review_text": "New one", "user_id": "C"}])
    run_all(conn, b1)
    run_all(conn, b2)
    assert counts(conn)["clean_reviews"] == 3
    assert conn.execute("SELECT review_text FROM clean_reviews WHERE review_id='r1'").fetchone()[0] == "Good one, edited"
    assert counts(conn)["review_predictions"] == 3   # edited review was re-scored, nothing orphaned


def test_schema_problem_is_rejected_and_logged(conn, tmp_path):
    """FAILURE PATH: file missing a required column is not loaded at all."""
    p = write_csv(tmp_path / "bad.csv", [{"review_id": "r1", "review_text": "x"}],
                  columns=["review_id", "product_id", "review_text"])
    with pytest.raises(SchemaError):
        ingest_file(conn, p)
    assert counts(conn)["raw_reviews"] == 0
    row = conn.execute("SELECT status, error FROM ingestion_log").fetchone()
    assert row["status"] == "failed" and "missing required columns" in row["error"]
