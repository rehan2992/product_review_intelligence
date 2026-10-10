# Product Review Intelligence

Ingest product reviews, clean them, score **sentiment + topic with confidence**, publish **SQL-ready aggregates**,
and **detect sudden sentiment changes (drift)**. Python + SQL, synthetic data only, runs from a clean setup with no
downloads and no secrets.

## 1. Problem statement
Reviews arrive as messy CSV batches (duplicates, bad ratings/dates, HTML, empty text, non-English text).
We need trustworthy sentiment/topic data with a confidence score, aggregates analysts can query, and an alert when
a product's sentiment changes suddenly (e.g. after a bad firmware update).

## 2. Approach
1. **Ingest** CSV batches into an untouched RAW layer (incremental, hash-checked, schema-checked).
2. **Clean**: Python validates/normalises each row, SQL dedupes and upserts; every rejected row keeps a reason.
3. **Enrich** with an AI model behind a `SentimentModel` interface: label + confidence, plus a topic.
   Low confidence goes to a review queue; failures retry, then fall back.
4. **Aggregate** with SQL views (daily, rolling 7-day, topic x sentiment, queues).
5. **Monitor drift**: last 7 days vs the prior 28 days per product, written to `drift_alerts`.

## 3. Architecture / data flow
See [docs/architecture.md](docs/architecture.md) (Mermaid diagram) and [docs/design_note.md](docs/design_note.md).

```
CSV --ingest--> raw_reviews --clean--> clean_reviews (+ rejected_reviews) --enrich(AI)--> review_predictions
                                                                                              |
                          drift_alerts <--drift checks-- SQL views (aggregates) <-------------+
```

## 4. Technologies
Python 3.10+ (stdlib: `sqlite3`, `csv`), SQLite (window functions, `ON CONFLICT` upserts), pytest.
Optional: Hugging Face `transformers` + `torch` for the DistilBERT SST-2 backend. The default pipeline needs no model download; the optional HF backend downloads its model on first use.

## 5. Project structure
```
README.md  requirements.txt  requirements-hf.txt  Makefile  pytest.ini  .env.example  .gitignore
data/sample/        batch_1.csv, batch_2.csv   (synthetic, committed, reproducible)
sql/                01_create_tables  02_clean_reviews  03_aggregates  04_drift_checks
src/                generate_data  ingest  clean  enrich  aggregate  drift  pipeline  config  db
src/ai/             base (interface)  rule_model  hf_model  topics
tests/              cleaning, dedupe/idempotency/schema, AI failures, end-to-end drift
scripts/            drift_sweep.py  (measures drift detection/false-alarm rates)
docs/               architecture.md  design_note.md
```

## 6. Setup and run
```bash
git clone <your-repo-url> && cd product-review-intelligence
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m src.generate_data        # optional: regenerate data/sample (deterministic, seed 42)
python -m src.pipeline --reset     # run everything on data/sample/*.csv
python -m pytest -q                # 18 tests
```
Incremental demo (batch 2 overlaps batch 1 and contains edited reviews):
```bash
python -m src.pipeline --reset --files batch_1.csv
python -m src.pipeline --files batch_2.csv
python -m src.pipeline --files batch_1.csv batch_2.csv     # nothing changes (idempotent)
```
Optional real model: `pip install -r requirements-hf.txt && python -m src.pipeline --reset --backend hf`
(if the model cannot load, the pipeline falls back to the rule model and records that in `model_name`).
Config: copy `.env.example` to `.env` (all optional). No secrets are needed or committed.

Outputs: SQLite DB `data/reviews.db` (git-ignored); `output/*.csv` (one per view) and `output/drift_report.md`.
Try: `sqlite3 data/reviews.db "select * from product_summary;"`

## 7. Data model
| Table | Key columns |
|---|---|
| `raw_reviews` | raw_id, review_id, product_id, user_id, rating, review_text, review_date (all TEXT), batch_id, cleaned_at |
| `ingestion_log` | source_file, file_hash, status (loaded/failed), error |
| `clean_reviews` | review_id PK, product_id, rating INT 1-5 or NULL, review_text, review_date ISO, text_hash |
| `rejected_reviews` | raw row + `reject_reason` |
| `review_predictions` | review_id, sentiment_label, raw_label, sentiment_score, topic, topic_score, model_name/version, status, reason |
| `drift_alerts` | check_date, product_id, metric, baseline_value, current_value, threshold, severity, detail |

Views: `daily_sentiment_by_product`, `rolling_7d_negative_share`, `topic_sentiment_summary`, `product_summary`,
`low_confidence_queue`, `failed_predictions`, `rating_sentiment_disagreement`.

## 8. AI approach
* **Input:** cleaned review text, truncated to at most 2000 characters in the enrichment layer. The HF backend also tokenizes/truncates to its 512-token model limit.
* **Output:** the default rule-based model supports `positive|negative|neutral` with a confidence in `[0, 1]`; the optional DistilBERT SST-2 model is binary (`positive|negative`) with a score in `[0, 1]`. The SST-2 backend does not produce a true neutral class.
* **Topic:** keyword classifier (delivery, quality, price, support, battery, other) with a hit-share score.
* **Default model:** lexicon scorer with negation/intensifier handling. Confidence falls toward 0.5 when cues are absent
  or conflict (mixed reviews). **Optional:** DistilBERT SST-2.
* **Bad outcomes:** confidence < 0.65 -> `low_confidence`, label `uncertain`, raw guess kept, listed in `low_confidence_queue`;
  empty/too-short text, text with no letters, and text whose alphabetic characters are mostly non-ASCII -> `failed` before the model is called. This is a script heuristic, not general language detection; the current model setup is intended for English reviews. Model error -> retry once -> rule fallback -> `failed` if that also fails; malformed output -> `failed: invalid_model_output`.

## 9. Drift monitoring
Per product, last 7 days vs previous 28 days: negative-share jump (>=15 pts and z >= 2.5), label-mix PSI (>= 0.2, plus chi-square
significance), mean-confidence drop (>= 0.10), topic-share jump (>= 15 pts and z >= 4). Minimum sample sizes apply.
The generator plants a drift: product **P03** goes from ~15% to ~55% negative in the last 7 days after a "firmware update".

## 10. Assumptions
English reviews (non-English-script reviews are currently unsupported and recorded as failed predictions); one row = one review; `dd/mm/yyyy` is day-first; a missing rating is kept (NULL) but a present, invalid
rating rejects the row; same text + same user + same product under a different id is a duplicate; latest delivery of a
`review_id` wins; confidence threshold 0.65.

## 11. Tests (18)
`tests/test_cleaning.py` invalid rows rejected with reasons, normalisation, parsers.
`tests/test_dedup_idempotency.py` duplicates/near-duplicates, re-run idempotency, overlapping + edited batch, **bad schema file**.
`tests/test_ai.py` low-confidence routing, **model crash -> retry -> fallback**, **both models down**, **malformed output**, unsupported input.
`tests/test_pipeline_drift.py` planted drift caught on P03 only, **no alerts on stable data**, schema checks, rerun does not duplicate alerts.
Tests use a fake model (no downloads) and temp databases.

## 12. Sample output (real run, seed 42)
```
clean   raw_processed=4390 clean_added=3736 rejected_added=654
enrich  processed=3736 ok=3416 low_confidence=283 failed=37 fallback_batches=0
drift   3 alert(s)
   [HIGH] P03 negative_share: negative share 15.1% -> 57.1% (z=5.7, n=42 vs 159)
   [HIGH] P03 label_psi: label mix shifted, PSI=0.97
   [HIGH] P03 topic_share:battery: 'battery' mentions 14.5% -> 54.8% (z=5.5)
```
Rejections: duplicate_review_id 426, near_duplicate 68, empty_text 65, invalid_rating 47, invalid_date 20,
missing_product_id 14, future_date 14. Failed AI: 37 (non-English script).
Rolling 7-day negative share for P03 (`rolling_7d_negative_share`): 0.22 (Sep 22) -> 0.32 (Sep 25) -> 0.57 (Sep 30).
Threshold check (`python scripts/drift_sweep.py --seeds 40`): planted drift found 40/40; stable data raised an alert in 2/40 runs.

## 13. Known limitations
* Synthetic data and the lexicon share vocabulary, so sentiment accuracy here is optimistic; no labelled evaluation yet.
* English only; no sarcasm handling; HF SST-2 is binary (ambiguity appears only as low score).
* Fixed drift windows, no seasonality; with many product/topic tests a few false alarms are statistically expected.
* The fallback retries the broken primary for every batch (no circuit breaker).
* SQLite: single writer, whole-file DB.

## 14. What I would improve for production
Postgres/warehouse + dbt models; Airflow/cron scheduling and Slack/PagerDuty alerts on `drift_alerts`; a labelled
evaluation set and model monitoring (MLflow); circuit breaker and batching/queueing for model calls; human labelling
loop fed by `low_confidence_queue`; multilingual model; seasonality-aware drift (e.g. STL residuals / CUSUM); data
contracts and schema evolution; CI running the tests on every push.
