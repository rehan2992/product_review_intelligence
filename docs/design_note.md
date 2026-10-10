# Design note

**Goal:** turn messy product-review feeds into trustworthy sentiment/topic data with confidence, SQL-ready
aggregates, and a way to notice when sentiment suddenly shifts.

## Key decisions and why
1. **Layered tables (raw -> clean -> curated).** Raw is never modified, so cleaning rules can change and be
   replayed. Rejected rows are stored with a reason instead of dropped: data-quality problems become visible
   and countable (654 rejected rows in the sample run).
2. **SQLite, stdlib only.** The reviewer can run it with no database server and no downloads. Trade-off: no
   concurrent writers and weaker types; at scale this becomes Postgres/a warehouse with the same SQL layering.
3. **Python for row-level parsing, SQL for set logic.** Date/rating parsing and HTML stripping are awkward in
   SQLite; dedupe, upsert and aggregates are natural in SQL (window functions, `ON CONFLICT`). The SQL step runs in
   the same transaction as the Python step, so a failure leaves nothing half-cleaned.
4. **Idempotency by state.** Files are hashed (re-delivered file = skipped); cleaning only touches un-cleaned raw
   rows; scoring only touches reviews without a prediction; an edited review (same id, new text) deletes its old
   prediction so it is re-scored; drift alerts are replaced per check date.
5. **AI behind an interface (`SentimentModel`).** The pipeline never imports a model library. Default backend is a
   dependency-free lexicon scorer (runs anywhere, deterministic, also the fallback); a Hugging Face DistilBERT
   backend is optional. Trade-off: the lexicon is weaker on real language than a transformer.
6. **Confidence threshold instead of forcing a label.** Scores below 0.65 become `uncertain` (the model's raw
   guess is kept in `raw_label`) and appear in `low_confidence_queue` for humans. Forcing a label would hide the
   mixed reviews that matter most. Model crash -> retry once -> fallback model -> `failed`; malformed output
   (bad label, score outside 0..1, wrong count) is never stored as truth.
7. **Drift = last 7 days vs prior 28 days, per product,** using four signals (negative share, label-mix PSI,
   mean confidence, topic share). Each alert needs minimum sample sizes and a significance test (z-test, and a
   chi-square gate on PSI). I first used raw PSI thresholds and saw false alarms on stable data with ~45 reviews
   per window; smoothing + significance testing fixed that. `scripts/drift_sweep.py` measures the result:
   planted drift found in 40/40 seeds, 2/40 stable runs raised an alert (statistical flukes, ~0.5% of product-windows).

## Alternatives considered
- API LLM for sentiment: better quality, but cost, privacy and non-reproducibility for a reviewer. Left as a
  new class implementing `SentimentModel`.
- Streaming (Kafka): unnecessary for daily batch reviews; batch + incremental keeps it simple.
- dbt/Airflow: right for production, too heavy for a screening exercise.

## Limitations
- Synthetic data and lexicon share vocabulary, so accuracy numbers on this data are optimistic. Real-data
  evaluation against labelled reviews is the first thing to add.
- English-focused input validation: alphabetic text with less than 80% ASCII letters is rejected as `unsupported_input:non_english_script`. This is a script heuristic, not reliable language detection. The optional DistilBERT SST-2 backend is binary and does not produce a true neutral label. Sarcasm is not handled.
- Drift windows are fixed and calendar-naive (no seasonality / day-of-week adjustment); many tests per run
  means some false alarms are statistically expected.
- Day-first date parsing for `dd/mm/yyyy` is an assumption; a feed with US dates would be misread.
