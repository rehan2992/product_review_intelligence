from datetime import date

from src.clean import clean_pending, parse_date, parse_rating, validate_row
from src.ingest import ingest_file
from tests.conftest import write_csv


def reasons(conn):
    return {r["review_id"]: r["reject_reason"] for r in conn.execute("SELECT * FROM rejected_reviews")}


def test_invalid_records_are_rejected_with_reason_not_dropped(conn, tmp_path):
    """FAILURE PATH: bad rows land in rejected_reviews with a reason; good rows survive."""
    p = write_csv(tmp_path / "b.csv", [
        {"review_id": "ok1", "review_text": "Great product"},
        {"review_id": "bad_rating", "review_text": "fine", "rating": "7"},
        {"review_id": "empty", "review_text": "   "},
        {"review_id": "bad_date", "review_text": "fine", "review_date": "not a date"},
        {"review_id": "future", "review_text": "fine", "review_date": "2099-01-01"},
        {"review_id": "no_product", "review_text": "fine", "product_id": ""},
        {"review_id": "", "review_text": "no id at all"},
    ])
    ingest_file(conn, p)
    stats = clean_pending(conn)
    assert stats["clean_added"] == 1
    assert reasons(conn) == {"bad_rating": "invalid_rating", "empty": "empty_text", "bad_date": "invalid_date",
                             "future": "future_date", "no_product": "missing_product_id", "": "missing_review_id"}
    assert conn.execute("SELECT COUNT(*) FROM raw_reviews").fetchone()[0] == 7  # raw layer keeps everything


def test_normalisation_html_whitespace_word_rating_and_date_formats(conn, tmp_path):
    p = write_csv(tmp_path / "b.csv", [
        {"review_id": "r1", "review_text": "<p>  Nice   &amp; solid\n</p>", "rating": "five",
         "review_date": "05/03/2026", "product_id": " p01 "},
        {"review_id": "r2", "review_text": "No rating given", "rating": ""},
    ])
    ingest_file(conn, p)
    clean_pending(conn)
    r1 = conn.execute("SELECT * FROM clean_reviews WHERE review_id='r1'").fetchone()
    assert (r1["review_text"], r1["rating"], r1["review_date"], r1["product_id"]) == \
           ("Nice & solid", 5, "2026-03-05", "P01")
    assert conn.execute("SELECT rating FROM clean_reviews WHERE review_id='r2'").fetchone()[0] is None


def test_parsers_unit():
    assert parse_rating("4.0") == (4, None)
    assert parse_rating("N/A") == (None, None)
    assert parse_rating("0") == (None, "invalid_rating")
    assert parse_date("Mar 05, 2026") == date(2026, 3, 5)
    assert parse_date("31/02/2026") is None
    assert validate_row({"review_id": "x", "product_id": "p", "review_text": "t ok", "review_date": "2026-01-01"})[1] is None
