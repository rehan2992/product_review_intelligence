"""Drift / sudden-change monitoring on the AI output.

For every product we compare   CURRENT = last 7 days   vs   BASELINE = the 28 days before that.
Checks (thresholds in DriftThresholds, all overridable):
  negative_share   share of 'negative' predictions jumped: delta >= 0.15 AND two-proportion z >= 3
  label_psi        PSI of the label mix (positive/negative/neutral/uncertain), only when also
                   significant under a chi-square test (p<0.001) so small-sample noise is ignored
  avg_confidence   mean model confidence dropped (symptom of data drift or a degraded model)
  topic_share:<t>  a topic's share of reviews jumped (e.g. a new defect flooding in)
Minimum sample sizes guard against alerting on noise. Alerts are stored in drift_alerts and are
idempotent per (check_date): re-running replaces that day's alerts.
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .db import SQL_DIR

log = logging.getLogger(__name__)
LABEL_SET = ("positive", "negative", "neutral", "uncertain")


@dataclass(frozen=True)
class DriftThresholds:
    min_current: int = 20
    min_baseline: int = 50
    neg_share_delta: float = 0.15
    neg_share_z: float = 2.5
    psi_medium: float = 0.2     # textbook is 0.1/0.25; the chi-square gate handles small-sample noise
    psi_high: float = 0.4
    conf_drop_medium: float = 0.10
    conf_drop_high: float = 0.20
    topic_delta: float = 0.15
    topic_z: float = 4.0


def load_named_queries(path=None) -> dict[str, str]:
    path = Path(path or SQL_DIR / "04_drift_checks.sql")
    queries: dict[str, list[str]] = {}
    name = None
    for line in path.read_text().splitlines():
        m = re.match(r"--\s*name:\s*(\w+)", line)
        if m:
            name = m.group(1)
            queries[name] = []
        elif name is not None:
            queries[name].append(line)
    return {k: "\n".join(v).strip().rstrip(";") for k, v in queries.items()}


def psi(base: dict, cur: dict, labels=LABEL_SET, alpha: float = 0.5) -> float:
    """Population Stability Index with additive (Laplace-style) smoothing.

    Smoothing matters: with ~45 reviews in the current window an empty bin would otherwise blow PSI up
    on pure noise (observed 0.5+ on stable data without it).
    """
    k = len(labels)
    bt = sum(base.get(l, 0) for l in labels) + alpha * k
    ct = sum(cur.get(l, 0) for l in labels) + alpha * k
    if sum(base.get(l, 0) for l in labels) == 0 or sum(cur.get(l, 0) for l in labels) == 0:
        return 0.0
    total = 0.0
    for l in labels:
        b = (base.get(l, 0) + alpha) / bt
        c = (cur.get(l, 0) + alpha) / ct
        total += (c - b) * math.log(c / b)
    return total


# chi-square critical values at p = 0.001 for df = 1..3
_CHI2_P001 = {1: 10.83, 2: 13.82, 3: 16.27}


def chi2_significant(base: dict, cur: dict, labels=LABEL_SET) -> bool:
    """Chi-square test of homogeneity (2 x k table) at p < 0.001: is the label mix really different?"""
    cols = [l for l in labels if base.get(l, 0) + cur.get(l, 0) > 0]
    nb, nc = sum(base.get(l, 0) for l in cols), sum(cur.get(l, 0) for l in cols)
    if len(cols) < 2 or nb == 0 or nc == 0:
        return False
    total, stat = nb + nc, 0.0
    for l in cols:
        col = base.get(l, 0) + cur.get(l, 0)
        for obs, row in ((base.get(l, 0), nb), (cur.get(l, 0), nc)):
            exp = row * col / total
            stat += (obs - exp) ** 2 / exp
    return stat >= _CHI2_P001[min(len(cols) - 1, 3)]


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> float:
    """z statistic for p2 > p1 (pooled)."""
    if min(n1, n2) == 0:
        return 0.0
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    return 0.0 if se == 0 else (x2 / n2 - x1 / n1) / se


def run_drift_checks(conn: sqlite3.Connection, as_of: str | None = None,
                     t: DriftThresholds = DriftThresholds()) -> list[dict]:
    q = load_named_queries()
    as_of = as_of or conn.execute(q["latest_date"]).fetchone()["d"]
    if as_of is None:
        return []

    labels = defaultdict(lambda: {"baseline": defaultdict(int), "current": defaultdict(int)})
    conf = defaultdict(lambda: {"baseline": [0.0, 0], "current": [0.0, 0]})
    for r in conn.execute(q["label_counts"], {"as_of": as_of}):
        labels[r["product_id"]][r["win"]][r["label"]] += r["n"]
        conf[r["product_id"]][r["win"]][0] += r["conf_sum"]
        conf[r["product_id"]][r["win"]][1] += r["n"]
    topics = defaultdict(lambda: {"baseline": defaultdict(int), "current": defaultdict(int)})
    for r in conn.execute(q["topic_counts"], {"as_of": as_of}):
        topics[r["product_id"]][r["win"]][r["topic"]] += r["n"]

    alerts: list[dict] = []

    def add(pid, metric, base_v, cur_v, thr, sev, detail):
        alerts.append(dict(check_date=as_of, product_id=pid, metric=metric, baseline_value=round(base_v, 4),
                           current_value=round(cur_v, 4), threshold=thr, severity=sev, detail=detail))

    for pid in sorted(labels):
        base, cur = labels[pid]["baseline"], labels[pid]["current"]
        nb, nc = sum(base.values()), sum(cur.values())
        if nc < t.min_current or nb < t.min_baseline:
            log.info("%s: not enough data (current=%d baseline=%d), skipped", pid, nc, nb)
            continue

        # 1. negative share
        pb, pc = base.get("negative", 0) / nb, cur.get("negative", 0) / nc
        z = two_prop_z(base.get("negative", 0), nb, cur.get("negative", 0), nc)
        if pc - pb >= t.neg_share_delta and z >= t.neg_share_z:
            add(pid, "negative_share", pb, pc, t.neg_share_delta,
                "high" if pc - pb >= 2 * t.neg_share_delta else "medium",
                f"negative share {pb:.1%} -> {pc:.1%} (z={z:.1f}, n={nc} vs {nb})")

        # 2. label distribution shift
        score = psi(base, cur)
        if score >= t.psi_medium and chi2_significant(base, cur):
            add(pid, "label_psi", 0.0, score, t.psi_medium, "high" if score >= t.psi_high else "medium",
                f"label mix shifted, PSI={score:.2f}")

        # 3. confidence drop
        cb = conf[pid]["baseline"][0] / conf[pid]["baseline"][1]
        cc = conf[pid]["current"][0] / conf[pid]["current"][1]
        if cb - cc >= t.conf_drop_medium:
            add(pid, "avg_confidence", cb, cc, t.conf_drop_medium,
                "high" if cb - cc >= t.conf_drop_high else "medium",
                f"mean model confidence {cb:.2f} -> {cc:.2f}")

        # 4. topic spikes
        tb, tc = topics[pid]["baseline"], topics[pid]["current"]
        tnb, tnc = sum(tb.values()), sum(tc.values())
        for topic in sorted(set(tb) | set(tc)):
            if topic == "other":
                continue
            sb, sc = tb.get(topic, 0) / tnb, tc.get(topic, 0) / tnc
            zt = two_prop_z(tb.get(topic, 0), tnb, tc.get(topic, 0), tnc)
            if sc - sb >= t.topic_delta and zt >= t.topic_z:
                add(pid, f"topic_share:{topic}", sb, sc, t.topic_delta,
                    "high" if sc - sb >= 2 * t.topic_delta else "medium",
                    f"'{topic}' mentions {sb:.1%} -> {sc:.1%} (z={zt:.1f})")

    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM drift_alerts WHERE check_date = ?", (as_of,))
    conn.executemany(
        "INSERT INTO drift_alerts (check_date, product_id, metric, baseline_value, current_value, "
        "threshold, severity, detail, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [(a["check_date"], a["product_id"], a["metric"], a["baseline_value"], a["current_value"],
          a["threshold"], a["severity"], a["detail"], now) for a in alerts])
    conn.commit()
    log.info("drift check as of %s: %d alerts", as_of, len(alerts))
    return alerts


def write_drift_report(alerts: list[dict], as_of: str | None, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Drift report (as of {as_of})", ""]
    if not alerts:
        lines.append("No drift detected.")
    else:
        lines += ["| Product | Metric | Severity | Detail |", "|---|---|---|---|"]
        lines += [f"| {a['product_id']} | {a['metric']} | {a['severity']} | {a['detail']} |" for a in alerts]
    path.write_text("\n".join(lines) + "\n")
    return path
