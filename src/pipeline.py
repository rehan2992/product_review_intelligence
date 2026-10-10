"""End-to-end runner:  ingest -> clean -> enrich -> aggregate -> drift -> report.

    python -m src.pipeline --reset                      # full run on data/sample/*.csv
    python -m src.pipeline --files batch_1.csv          # incremental: only these files
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import aggregate, clean, db, drift, enrich, ingest
from .ai import build_models
from .config import Config, load_config

log = logging.getLogger("pipeline")


def run(cfg: Config, files=None, reset: bool = False, as_of: str | None = None,
        primary=None, fallback=None) -> dict:
    if reset and cfg.db_path.exists():
        cfg.db_path.unlink()
    conn = db.connect(cfg.db_path)
    db.init_schema(conn)

    paths = [cfg.data_dir / f for f in files] if files else sorted(cfg.data_dir.glob("*.csv"))
    summary: dict = {"ingest": [], "ingest_errors": []}
    for p in paths:
        try:
            summary["ingest"].append(ingest.ingest_file(conn, p))
        except (ingest.SchemaError, FileNotFoundError) as exc:
            log.error("INGEST FAILED: %s", exc)
            summary["ingest_errors"].append(str(exc))

    summary["clean"] = clean.clean_pending(conn)

    if primary is None or fallback is None:
        primary, fallback = build_models(cfg.sentiment_backend, cfg.hf_model_name)
    summary["enrich"] = enrich.enrich_pending(conn, primary, fallback, cfg.confidence_threshold, cfg.batch_size)

    aggregate.build_aggregates(conn)
    alerts = drift.run_drift_checks(conn, as_of)
    summary["alerts"] = alerts
    as_of_used = alerts[0]["check_date"] if alerts else as_of
    drift.write_drift_report(alerts, as_of_used, cfg.output_dir / "drift_report.md")
    aggregate.export_aggregates(conn, cfg.output_dir)
    summary["totals"] = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                         for t in ("raw_reviews", "clean_reviews", "rejected_reviews", "review_predictions", "drift_alerts")}
    conn.close()
    return summary


def print_summary(s: dict) -> None:
    print("\n=== PIPELINE SUMMARY ===")
    for i in s["ingest"]:
        print(f"ingest  {i['file']:<18} {i['status']:<8} rows={i['rows']}")
    for e in s["ingest_errors"]:
        print(f"ingest  ERROR {e}")
    c, e = s["clean"], s["enrich"]
    print(f"clean   raw_processed={c['raw_processed']} clean_added={c['clean_added']} rejected_added={c['rejected_added']}")
    print(f"enrich  processed={e['processed']} ok={e['ok']} low_confidence={e['low_confidence']} "
          f"failed={e['failed']} fallback_batches={e['fallback_batches']}")
    print("totals ", s["totals"])
    print(f"drift   {len(s['alerts'])} alert(s)")
    for a in s["alerts"]:
        print(f"   [{a['severity'].upper():<6}] {a['product_id']} {a['metric']}: {a['detail']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="SQLite path (default: DB_PATH or data/reviews.db)")
    ap.add_argument("--data-dir", help="folder with input CSV files")
    ap.add_argument("--files", nargs="*", help="only ingest these files (names inside data-dir)")
    ap.add_argument("--reset", action="store_true", help="delete the database first")
    ap.add_argument("--backend", choices=["rule", "hf"], help="sentiment backend")
    ap.add_argument("--as-of", help="drift reference date YYYY-MM-DD (default: latest review date)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config(db_path=Path(args.db) if args.db else None,
                      data_dir=Path(args.data_dir) if args.data_dir else None,
                      sentiment_backend=args.backend)
    summary = run(cfg, files=args.files, reset=args.reset, as_of=args.as_of)
    print_summary(summary)
    return 1 if summary["ingest_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
