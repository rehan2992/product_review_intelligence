# Architecture and data flow

```mermaid
flowchart TD
    G[generate_data.py<br/>synthetic messy CSVs] --> F[(data/sample/*.csv)]
    F -->|1 ingest: hash check, schema check| RAW[(raw_reviews<br/>as received, TEXT)]
    F -. schema error .-> LOG[(ingestion_log: failed)]
    RAW -->|2 clean: Python validate + SQL dedupe/upsert| CLEAN[(clean_reviews)]
    RAW -->|invalid / duplicate rows| REJ[(rejected_reviews + reason)]
    CLEAN -->|3 enrich: only rows without a prediction| AI{{SentimentModel interface}}
    AI --> RULE[rule-lexicon<br/>default + fallback]
    AI --> HF[HF transformer<br/>optional]
    AI -->|label + confidence + topic| PRED[(review_predictions<br/>ok / low_confidence / failed)]
    PRED -->|4 SQL views| AGG[daily_sentiment_by_product<br/>rolling_7d_negative_share<br/>topic_sentiment_summary<br/>low_confidence_queue<br/>rating_sentiment_disagreement]
    AGG -->|5 drift: last 7d vs prior 28d| ALERT[(drift_alerts)]
    ALERT --> REP[output/drift_report.md + CSV exports]
```

Plain-text version

```
CSV batches --ingest--> RAW --clean--> CLEAN (+ REJECTED) --enrich(AI)--> PREDICTIONS
                                                                              |
                                              SQL views (aggregates) <--------+
                                                    |
                                              drift checks --> drift_alerts --> report
```

| Layer | Table | Purpose |
|---|---|---|
| Raw | `raw_reviews`, `ingestion_log` | Exact copy of input plus batch id; lets us replay cleaning |
| Clean | `clean_reviews`, `rejected_reviews` | Typed, deduplicated data; every dropped row keeps a reason |
| Curated | `review_predictions` | Sentiment, confidence, topic, model name/version, status |
| Serving | SQL views | Aggregates for dashboards |
| Monitoring | `drift_alerts` | Output of drift checks |

Incrementality is driven by state, not by timestamps: `raw_reviews.cleaned_at IS NULL` selects rows to clean,
and `LEFT JOIN review_predictions ... IS NULL` selects reviews to score.
