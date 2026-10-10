"""Synthetic, deliberately messy product-review generator (no real or personal data).

Writes data/sample/batch_1.csv and batch_2.csv. The batches OVERLAP by ~6 days (re-delivered rows plus a few
edited reviews) to exercise incremental loading. Injected problems:
  duplicate review_ids, near-duplicates, empty text, blank/invalid/word ratings, mixed date formats,
  future dates, missing product ids, HTML + whitespace noise, emojis, non-English (Hindi) text,
  mixed-sentiment reviews (-> low confidence)
PLANTED DRIFT: product P03's negative share jumps from ~15% to 55% in the last 7 days, mostly about
a "firmware update" that wrecked battery life (drift=False disables it, for the "no false alarm" test).
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

PRODUCTS = [f"P{i:02d}" for i in range(1, 11)]
DRIFT_PRODUCT = "P03"
DRIFT_DAYS = 7
END_DATE = date(2026, 9, 30)
FIELDS = ["review_id", "product_id", "user_id", "rating", "review_text", "review_date"]

POS = {
    "delivery": ["Delivery was fast and the package arrived early.", "Arrived well packed and right on time.",
                 "Shipping was quick, very happy with the delivery."],
    "quality": ["Excellent build quality, feels solid and premium.", "Great quality for the money, works perfectly.",
                "Really well made, I love it."],
    "price": ["Great value for the price.", "Very affordable and worth every penny.", "Fantastic deal, well worth it."],
    "support": ["Customer support was helpful and resolved my issue quickly.",
                "Friendly support team, excellent service.", "Support was great and the refund was easy."],
    "battery": ["Battery life is amazing and lasts all day.", "Great battery, charges fast.",
                "Battery easily lasts two days, really impressed."],
}
NEG = {
    "delivery": ["Delivery was terribly slow and the box arrived damaged.", "Shipping took forever, really disappointed.",
                 "The package arrived late and was badly crushed."],
    "quality": ["Poor build quality, it feels cheap and flimsy.", "Stopped working after a week, awful quality.",
                "Broke within days, completely useless."],
    "price": ["Way too expensive for what you get.", "Overpriced and not worth the money.",
              "Terrible value, a total waste of money."],
    "support": ["Customer support was unhelpful and never replied.", "Terrible service, the support team was rude.",
                "Support ignored me, worst experience."],
    "battery": ["Battery drains in a couple of hours, terrible battery life.",
                "Battery died after an hour, really disappointing.", "Awful battery, charging takes forever."],
}
FIRMWARE_NEG = ["Since the latest firmware update the battery drains overnight, awful.",
                "The new firmware update broke the battery, very frustrating.",
                "After the firmware update the battery is terrible and it keeps dying."]
NEUTRAL = ["It is okay, does what it says.", "Average product, nothing special.",
           "Arrived today, haven't tried it yet.", "Decent for everyday use."]
HINDI = ["बहुत अच्छा उत्पाद, जल्दी पहुंचा", "बेकार सामान, पैसे बर्बाद"]


def _text(rng, kind, firmware=False):
    topics = list(POS)
    if kind == "positive":
        return rng.choice(POS[rng.choice(topics)])
    if kind == "negative":
        if firmware and rng.random() < 0.6:
            return rng.choice(FIRMWARE_NEG)
        return rng.choice(NEG[rng.choice(topics)])
    if kind == "neutral":
        return rng.choice(NEUTRAL)
    a, b = rng.sample(topics, 2)  # mixed: praise one thing, criticise another
    neg = rng.choice(NEG[b])
    return f"{rng.choice(POS[a])} However, {neg[0].lower() + neg[1:]}"


def _rating(rng, kind):
    base = {"positive": [5, 4], "negative": [1, 2], "neutral": [3], "mixed": [3, 2, 4]}[kind]
    r = rng.choice(base)
    return rng.randint(1, 5) if rng.random() < 0.06 else r  # label noise -> rating/sentiment disagreements


def _dirty(rng, rec):
    text, rating, d = rec["text"], str(rec["rating"]), rec["date"].isoformat()
    if rng.random() < 0.04:
        text = f"<p>{text}</p>"
    if rng.random() < 0.04:
        text = f"  {text.replace(' ', '  ', 2)}  \n"
    if rng.random() < 0.05:
        text += " " + rng.choice(["👍", "😍"] if rec["kind"] == "positive" else ["😡", "👎"])
    if rng.random() < 0.01:
        text = rng.choice(HINDI)
    if rng.random() < 0.015:
        text = rng.choice(["", "   ", "N/A"[:0]])
    x = rng.random()
    if x < 0.02:
        rating = ""
    elif x < 0.04:
        rating = ["one", "two", "three", "four", "five"][rec["rating"] - 1]
    elif x < 0.055:
        rating = rng.choice(["0", "7", "-1", "abc", "N/A", "10"])
    y = rng.random()
    if y < 0.08:
        d = rec["date"].strftime("%d/%m/%Y")
    elif y < 0.12:
        d = rec["date"].strftime("%b %d, %Y")
    elif y < 0.124:
        d = "2099-01-01"
    elif y < 0.128:
        d = rng.choice(["31/02/2026", "yesterday", "not a date"])
    product = "" if rng.random() < 0.003 else rec["product"]
    return {"review_id": rec["review_id"], "product_id": product, "user_id": rec["user"],
            "rating": rating, "review_text": text, "review_date": d}


def generate(out_dir, seed: int = 42, end: date = END_DATE, days: int = 60, drift: bool = True) -> list[Path]:
    rng = random.Random(seed)
    base_neg = {p: rng.uniform(0.12, 0.22) for p in PRODUCTS}
    records, n = [], 0
    for offset in range(days - 1, -1, -1):
        day = end - timedelta(days=offset)
        for pid in PRODUCTS:
            in_drift = drift and pid == DRIFT_PRODUCT and offset < DRIFT_DAYS
            p_neg = 0.55 if in_drift else base_neg[pid]
            for _ in range(rng.randint(4, 9)):
                n += 1
                u = rng.random()
                kind = ("negative" if u < p_neg else "mixed" if u < p_neg + 0.08
                        else "neutral" if u < p_neg + 0.18 else "positive")
                records.append({"review_id": f"R{n:06d}", "product": pid, "user": f"U{rng.randint(1, 800):04d}",
                                "kind": kind, "text": _text(rng, kind, firmware=in_drift),
                                "rating": _rating(rng, kind), "date": day, "offset": offset})

    rows = [(_dirty(rng, r), r["offset"]) for r in records]
    extra = []
    for row, off in rows:                       # near-duplicates: new review_id, same user/product/text
        if rng.random() < 0.012:
            n += 1
            extra.append(({**row, "review_id": f"R{n:06d}"}, off))
    for row, off in rows:                       # exact re-submissions inside the same feed
        if rng.random() < 0.015:
            extra.append((dict(row), off))
    rows += extra
    rng.shuffle(rows)

    overlap_edit = 0
    batch1 = [r for r, off in rows if off >= 15]
    batch2 = []
    for r, off in rows:
        if off <= 20:
            r = dict(r)
            if 15 <= off <= 20 and overlap_edit < 5 and r["review_text"].strip() and rng.random() < 0.05:
                r["review_text"] += " Update: still happy after a month."   # edited review re-delivered
                overlap_edit += 1
            batch2.append(r)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, batch in (("batch_1.csv", batch1), ("batch_2.csv", batch2)):
        p = out / name
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(batch)
        paths.append(p)
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate synthetic review CSVs")
    ap.add_argument("--out", default="data/sample")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-drift", action="store_true")
    a = ap.parse_args(argv)
    for p in generate(a.out, seed=a.seed, drift=not a.no_drift):
        print("wrote", p)


if __name__ == "__main__":
    main()
