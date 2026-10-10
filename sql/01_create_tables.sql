-- ===== RAW layer: data exactly as received (all TEXT) =====
CREATE TABLE IF NOT EXISTS ingestion_log (
    source_file TEXT PRIMARY KEY,
    file_hash   TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    row_count   INTEGER,
    status      TEXT NOT NULL CHECK (status IN ('loaded','failed')),
    error       TEXT,
    loaded_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_reviews (
    raw_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id   TEXT,
    product_id  TEXT,
    user_id     TEXT,
    rating      TEXT,
    review_text TEXT,
    review_date TEXT,
    source_file TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    loaded_at   TEXT NOT NULL,
    cleaned_at  TEXT                -- NULL = not yet processed (drives incremental cleaning)
);

-- ===== STAGING / CLEAN layer =====
CREATE TABLE IF NOT EXISTS clean_reviews (
    review_id   TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL,
    user_id     TEXT,
    rating      INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    review_text TEXT NOT NULL,
    review_date TEXT NOT NULL,      -- ISO yyyy-mm-dd
    text_hash   TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_clean_product_date ON clean_reviews (product_id, review_date);

CREATE TABLE IF NOT EXISTS rejected_reviews (
    reject_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id        INTEGER,
    review_id     TEXT,
    product_id    TEXT,
    user_id       TEXT,
    rating        TEXT,
    review_text   TEXT,
    review_date   TEXT,
    source_file   TEXT,
    batch_id      TEXT,
    reject_reason TEXT NOT NULL,
    rejected_at   TEXT NOT NULL
);

-- ===== CURATED layer: AI output =====
CREATE TABLE IF NOT EXISTS review_predictions (
    review_id       TEXT PRIMARY KEY REFERENCES clean_reviews (review_id),
    sentiment_label TEXT,           -- positive | negative | neutral | uncertain (low confidence)
    raw_label       TEXT,           -- what the model actually said, before confidence routing
    sentiment_score REAL,           -- model confidence 0..1
    topic           TEXT,
    topic_score     REAL,
    model_name      TEXT,
    model_version   TEXT,
    status          TEXT NOT NULL CHECK (status IN ('ok','low_confidence','failed')),
    reason          TEXT,
    processed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pred_status ON review_predictions (status);

-- ===== Monitoring =====
CREATE TABLE IF NOT EXISTS drift_alerts (
    alert_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    check_date     TEXT NOT NULL,
    product_id     TEXT NOT NULL,
    metric         TEXT NOT NULL,
    baseline_value REAL,
    current_value  REAL,
    threshold      REAL,
    severity       TEXT NOT NULL CHECK (severity IN ('medium','high')),
    detail         TEXT,
    created_at     TEXT NOT NULL
);
