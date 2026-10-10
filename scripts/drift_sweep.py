"""Empirical check of the drift thresholds: how often do we miss the planted drift / raise false alarms?

    python scripts/drift_sweep.py --seeds 40
Generates synthetic data for many seeds, WITH and WITHOUT the planted drift, runs the whole pipeline and
reports detection rate (recall) and false-alarm rate. Used to choose the defaults in DriftThresholds.
"""
import argparse
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import load_config          # noqa: E402
from src.generate_data import DRIFT_PRODUCT, generate  # noqa: E402
from src.pipeline import run                # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    n = ap.parse_args().seeds
    logging.disable(logging.CRITICAL)
    tmp = Path(tempfile.mkdtemp())
    detected = false_alarm_drift_runs = false_alarm_stable_runs = 0
    for seed in range(1, n + 1):
        for drift in (True, False):
            d = tmp / f"{'d' if drift else 's'}{seed}"
            generate(d, seed=seed, drift=drift)
            alerts = run(load_config(db_path=d / "x.db", data_dir=d, output_dir=tmp / "o"))["alerts"]
            if drift:
                detected += any(a["product_id"] == DRIFT_PRODUCT and a["metric"] == "negative_share" for a in alerts)
                false_alarm_drift_runs += any(a["product_id"] != DRIFT_PRODUCT for a in alerts)
            else:
                false_alarm_stable_runs += bool(alerts)
    print(f"seeds={n}")
    print(f"planted drift detected (negative_share on {DRIFT_PRODUCT}): {detected}/{n}")
    print(f"runs with a false alarm on OTHER products (drift data):    {false_alarm_drift_runs}/{n}")
    print(f"runs with any alert on stable data:                         {false_alarm_stable_runs}/{n}")


if __name__ == "__main__":
    main()
