# Product Review Intelligence

A Python and SQL pipeline for ingesting product reviews, cleaning messy data, performing sentiment and topic analysis with confidence scores, publishing SQL-ready aggregates, and detecting sudden sentiment drift.

The project uses synthetic review data and a reproducible SQLite pipeline. The default rule-based backend runs without downloading an ML model or requiring API secrets.

GitHub Repository: https://github.com/rehan2992/product_review_intelligence

## 1. Problem Statement

Product reviews often contain duplicate records, invalid ratings and dates, HTML, missing text, and unsupported languages. These issues make it difficult to derive reliable insights about customer sentiment and product quality.

This project addresses these challenges by building a pipeline that:

- Ingests and validates CSV review batches.
- Cleans and deduplicates review records.
- Predicts sentiment and identifies review topics.
- Assigns confidence scores and routes uncertain predictions for review.
- Stores structured data in SQLite and publishes SQL-ready aggregates.
- Detects significant changes in product sentiment and topic distributions.

## 2. Solution Overview

The pipeline consists of five main stages:

1. Ingestion: Loads CSV batches into an immutable raw layer, validates schemas, and tracks file hashes.
2. Cleaning: Normalizes review data, validates ratings and dates, removes duplicates, and records rejection reasons.
3. AI Enrichment: Predicts sentiment, confidence, and topic using a configurable model interface.
4. Aggregation: Generates SQL views for daily sentiment, rolling sentiment trends, topic analysis, and review queues.
5. Drift Detection: Compares recent review patterns with historical baselines and stores detected alerts in `drift_alerts`.

## 3. Architecture and Data Flow

See [docs/architecture.md](docs/architecture.md) for the architecture diagram and [docs/design_note.md](docs/design_note.md) for design decisions.

```text
CSV Batches
    |
    v
Ingestion and Schema Validation
    |
    v
raw_reviews + ingestion_log
    |
    v
Cleaning and Deduplication
    |
    +----------------------> rejected_reviews
    |
    v
clean_reviews
    |
    v
Sentiment and Topic Enrichment
    |
    v
review_predictions
    |
    v
SQL Aggregation Views
    |
    +----------------------> CSV Exports
    |
    v
Drift Detection
    |
    v
drift_alerts
```

## 4. Technology Stack

- Language: Python 3.10+
- Database: SQLite
- Data Processing: Python standard library (`csv`, `sqlite3`)
- Query and Analytics: SQL views, window functions, and upserts
- Testing: pytest
- Optional ML Backend: Hugging Face Transformers and PyTorch
- Model: DistilBERT fine-tuned on SST-2 for binary sentiment classification

The default rule-based backend does not require downloading model weights. The optional Hugging Face backend downloads the model on first use.

## 5. Project Structure

```text
product_review_intelligence/
├── README.md
├── requirements.txt
├── requirements-hf.txt
├── Makefile
├── pytest.ini
├── .env.example
├── .gitignore
├── data/
│   └── sample/
│       ├── batch_1.csv
│       └── batch_2.csv
├── docs/
│   ├── architecture.md
│   └── design_note.md
├── sql/
│   ├── 01_create_tables.sql
│   ├── 02_clean_reviews.sql
│   ├── 03_aggregates.sql
│   └── 04_drift_checks.sql
├── src/
│   ├── generate_data.py
│   ├── ingest.py
│   ├── clean.py
│   ├── enrich.py
│   ├── aggregate.py
│   ├── drift.py
│   ├── pipeline.py
│   ├── config.py
│   ├── db.py
│   └── ai/
│       ├── base.py
│       ├── rule_model.py
│       ├── hf_model.py
│       └── topics.py
├── tests/
│   ├── conftest.py
│   ├── test_ai.py
│   ├── test_cleaning.py
│   ├── test_dedup_idempotency.py
│   └── test_pipeline_drift.py
└── scripts/
    └── drift_sweep.py
```

## 6. Installation and Setup

### Prerequisites

- Python 3.10 or newer
- Git
- Internet access to clone the repository and install dependencies

### Windows (PowerShell)

```powershell
git clone https://github.com/rehan2992/product_review_intelligence.git
cd product_review_intelligence

py -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, use the environment's Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### macOS / Linux

```bash
git clone https://github.com/rehan2992/product_review_intelligence.git
cd product_review_intelligence

python3 -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt
```

## 7. Running the Pipeline

### Run the complete pipeline

```bash
python -m src.pipeline --reset
```

This command processes the sample CSV batches, updates the database, generates aggregates, runs drift checks, and exports the results.

Note: `--reset` resets pipeline state before processing. Use it for a clean demonstration, not when you need to preserve existing database state.

### Run the tests

```bash
python -m pytest -v
```

The project contains "18 tests" covering cleaning, deduplication, idempotency, model failures, confidence handling, and drift detection.

The tests use fake models and temporary databases, so they do not require downloading an ML model.

### Demonstrate incremental ingestion

```bash
python -m src.pipeline --reset --files batch_1.csv
python -m src.pipeline --files batch_2.csv
python -m src.pipeline --files batch_1.csv batch_2.csv
```

Batch 2 overlaps with batch 1 and includes edited reviews. Reprocessing the same batches demonstrates idempotency.

### Regenerate synthetic data (optional)

```bash
python -m src.generate_data
```

The generator uses seed 42 for reproducible sample data.

## 8. Optional Hugging Face Backend

To run the pipeline with the DistilBERT SST-2 sentiment model, install the optional dependencies:

```bash
python -m pip install -r requirements-hf.txt
python -m src.pipeline --reset --backend hf
```

The first run downloads the model weights and may take longer than the default pipeline.

If the Hugging Face model cannot be loaded or fails during inference, the pipeline is designed to retry and use the rule-based fallback. If both models fail, the prediction is recorded as failed.

## 9. AI Enrichment Design

### Input

The enrichment layer receives cleaned review text and truncates it to a maximum of 2,000 characters. The Hugging Face backend also applies its model token limit.

### Sentiment Output

The pipeline supports two sentiment backends:

| Feature | Rule-based backend | Hugging Face backend |
|---|---|---|
| Sentiment labels | Positive, negative, neutral | Positive, negative |
| Confidence | Score between 0 and 1 | Model score between 0 and 1 |
| Model download | Not required | Required on first use |
| Neutral class | Supported | Not supported as a true class |

The default backend uses a lexicon-based scorer with negation and intensifier handling. Its confidence moves toward 0.5 when sentiment cues are missing or conflicting.

The optional DistilBERT SST-2 model is binary. It does not generate a true neutral label.

### Topic Classification

A keyword-based classifier assigns one of these topics:

- `delivery`
- `quality`
- `price`
- `support`
- `battery`
- `other`

A topic score represents the classifier's hit-share score.

### Confidence and Failure Handling

- Predictions with confidence below `0.65` are routed to `low_confidence_queue`.
- Their final sentiment label is `uncertain`, while the raw prediction is retained.
- Empty or too-short text, text without alphabetic characters, and text whose alphabetic characters are mostly non-ASCII are rejected before model inference.
- Model errors trigger a retry followed by a rule-based fallback.
- If both models fail, the prediction is recorded as failed.
- Malformed model output is recorded with the reason `invalid_model_output`.

**Language limitation:** The current input validation uses a character-script heuristic, not general language detection. The current model setup is intended for English reviews; non-English-script reviews are currently unsupported and recorded as failed predictions.

## 10. Database Design

The pipeline uses SQLite to persist raw, cleaned, enriched, and monitoring data.

| Table | Purpose |
|---|---|
| `raw_reviews` | Stores ingested review records before cleaning |
| `ingestion_log` | Tracks source files, hashes, ingestion status, and errors |
| `clean_reviews` | Stores validated and normalized reviews |
| `rejected_reviews` | Stores rejected rows and their rejection reasons |
| `review_predictions` | Stores sentiment, confidence, topic, model information, and prediction status |
| `drift_alerts` | Stores detected drift events and their supporting metrics |

### SQL Views

The project provides the following analytical views:

- `daily_sentiment_by_product`
- `rolling_7d_negative_share`
- `topic_sentiment_summary`
- `product_summary`
- `low_confidence_queue`
- `failed_predictions`
- `rating_sentiment_disagreement`

These views make the processed data accessible for reporting and further analysis.

## 11. Drift Detection

The pipeline compares the most recent 7 days with the previous 28 days for each product.

| Metric | Detection condition |
|---|---|
| Negative sentiment share | Increase of at least 15 percentage points and z-score of at least 2.5 |
| Label distribution | Population Stability Index (PSI) of at least 0.2, with chi-square significance |
| Mean confidence | Decrease of at least 0.10 |
| Topic share | Increase of at least 15 percentage points and z-score of at least 4 |

Minimum sample-size requirements apply.

The synthetic data generator deliberately introduces a sentiment shift for product `P03`, simulating a negative response after a firmware update.

The drift detector records alerts in `drift_alerts` and exports a human-readable report.

## 12. Sample Results

The following figures represent the default rule-based pipeline run with seed 42.

```text
clean   raw_processed=4390 clean_added=3736 rejected_added=654
enrich  processed=3736 ok=3416 low_confidence=283 failed=37 fallback_batches=0
drift   3 alert(s)

[HIGH] P03 negative_share:
negative share 15.1% -> 57.1% (z=5.7, n=42 vs 159)

[HIGH] P03 label_psi:
label mix shifted, PSI=0.97

[HIGH] P03 topic_share:battery:
battery mentions 14.5% -> 54.8% (z=5.5)
```

### Data Quality Summary

| Metric | Count |
|---|---:|
| Raw records processed | 4,390 |
| Clean reviews added | 3,736 |
| Rejected records | 654 |
| Successful predictions | 3,416 |
| Low-confidence predictions | 283 |
| Failed predictions | 37 |
| Drift alerts | 3 |

The rejected records include duplicate review IDs, near-duplicates, empty text, invalid ratings, invalid dates, missing product IDs, and future dates.

The 37 failed predictions in this run were due to unsupported non-English-script input.

### Drift Detection Sweep

The following result was obtained from the project's synthetic drift sweep:

```text
Command: python scripts/drift_sweep.py --seeds 40

Planted drift detected: 40/40 runs
Stable-data runs with an alert: 2/40
```

These are results from synthetic experiments, not measurements of production performance.

## 13. Output Files

After a pipeline run, the project generates:

- `data/reviews.db` — SQLite database
- `output/*.csv` — exported SQL-view results
- `output/drift_report.md` — drift detection report

The database and generated outputs are excluded from Git through `.gitignore`.

To inspect the `product_summary` view, use a SQLite command-line client if installed:

```bash
sqlite3 data/reviews.db "SELECT * FROM product_summary;"
```

Alternatively, query the database using Python's built-in `sqlite3` module.

## 14. Testing and Reliability

The test suite covers:

- Invalid input validation and rejection reasons
- Text normalization and date parsing
- Duplicate and near-duplicate handling
- Incremental ingestion and idempotency
- Bad CSV schema handling
- Low-confidence prediction routing
- Model crash, retry, and fallback behavior
- Failure of both models
- Malformed model output
- Detection of planted drift
- Stable-data false-alert checks
- Database schema and duplicate-alert prevention

Run all tests with:

```bash
python -m pytest -v
```

## 15. Assumptions

- Sample reviews are synthetic.
- The intended language is English.
- One input row represents one review.
- Dates in `dd/mm/yyyy` format are interpreted as day-first.
- Missing ratings are retained as `NULL`; present but invalid ratings cause rejection.
- Duplicate detection considers matching text, user, and product even when the review ID differs.
- The latest delivery of a given `review_id` wins.
- The confidence threshold is `0.65`.

## 16. Known Limitations

- Synthetic data and the rule-based sentiment lexicon share vocabulary, so observed performance may be optimistic.
- There is no labelled real-world evaluation dataset yet.
- Sarcasm and nuanced context are not handled reliably.
- The optional SST-2 model is binary and does not provide a true neutral class.
- Non-English-script reviews are currently unsupported.
- Fixed drift windows do not account for seasonality.
- Testing many products and topics can produce occasional false alerts.
- The fallback mechanism does not yet use a circuit breaker.
- SQLite is best suited to this project's scale and has a single-writer limitation.

## 17. Future Improvements

Potential production improvements include:

- Moving to PostgreSQL or a data warehouse with dbt models.
- Scheduling jobs with Airflow or cron.
- Sending drift alerts through Slack or PagerDuty.
- Building a labelled evaluation dataset and monitoring model performance.
- Adding circuit breakers, batching, and inference queues.
- Using `low_confidence_queue` for human review and feedback.
- Adding multilingual sentiment support.
- Using seasonality-aware drift detection, such as STL residuals or CUSUM.
- Introducing stronger data contracts and schema evolution.
- Running tests automatically in CI on every push.

## 18. Reproducibility and Security

- Sample input data is synthetic and committed to the repository.
- The default pipeline requires no external model download.
- No API secrets are required for the default run.
- `.env` files, virtual environments, generated databases, caches, and pipeline outputs are excluded from Git.

---

Project: Product Review Intelligence  
Stack: Python, SQL, SQLite, pytest, optional Hugging Face Transformers  
Repository: https://github.com/rehan2992/product_review_intelligence