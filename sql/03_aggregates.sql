-- SQL-ready aggregates. Views are recreated on every run, so they always reflect current data.

DROP VIEW IF EXISTS v_scored_reviews;
CREATE VIEW v_scored_reviews AS
SELECT c.review_id, c.product_id, c.user_id, c.rating, c.review_date, c.review_text,
       p.sentiment_label, p.raw_label, p.sentiment_score, p.topic, p.topic_score,
       p.status, p.reason, p.model_name
FROM clean_reviews c
JOIN review_predictions p ON p.review_id = c.review_id;

DROP VIEW IF EXISTS daily_sentiment_by_product;
CREATE VIEW daily_sentiment_by_product AS
SELECT product_id,
       review_date,
       COUNT(*)                                              AS reviews,
       SUM(sentiment_label = 'positive')                     AS positive,
       SUM(sentiment_label = 'negative')                     AS negative,
       SUM(sentiment_label = 'neutral')                      AS neutral,
       SUM(sentiment_label = 'uncertain')                    AS uncertain,
       ROUND(1.0 * SUM(sentiment_label = 'positive') / COUNT(*), 3) AS positive_share,
       ROUND(1.0 * SUM(sentiment_label = 'negative') / COUNT(*), 3) AS negative_share,
       ROUND(AVG(rating), 2)                                 AS avg_rating,
       ROUND(AVG(sentiment_score), 3)                        AS avg_confidence
FROM v_scored_reviews
WHERE status <> 'failed'
GROUP BY product_id, review_date;

DROP VIEW IF EXISTS rolling_7d_negative_share;
CREATE VIEW rolling_7d_negative_share AS
SELECT product_id,
       review_date,
       reviews,
       SUM(negative) OVER w AS negative_7d,
       SUM(reviews)  OVER w AS reviews_7d,
       ROUND(1.0 * SUM(negative) OVER w / SUM(reviews) OVER w, 3) AS negative_share_7d
FROM daily_sentiment_by_product
WINDOW w AS (PARTITION BY product_id
             ORDER BY julianday(review_date)
             RANGE BETWEEN 6 PRECEDING AND CURRENT ROW);

DROP VIEW IF EXISTS topic_sentiment_summary;
CREATE VIEW topic_sentiment_summary AS
SELECT topic,
       sentiment_label,
       COUNT(*) AS reviews,
       ROUND(1.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY topic), 3) AS share_within_topic,
       ROUND(AVG(rating), 2) AS avg_rating
FROM v_scored_reviews
WHERE status <> 'failed'
GROUP BY topic, sentiment_label;

DROP VIEW IF EXISTS product_summary;
CREATE VIEW product_summary AS
SELECT product_id,
       COUNT(*)                                                  AS reviews,
       ROUND(AVG(rating), 2)                                     AS avg_rating,
       ROUND(1.0 * SUM(sentiment_label = 'negative') / COUNT(*), 3) AS negative_share,
       ROUND(1.0 * SUM(status = 'low_confidence') / COUNT(*), 3)    AS low_confidence_share
FROM v_scored_reviews
WHERE status <> 'failed'
GROUP BY product_id;

-- Human-in-the-loop queue: reviews the model was not sure about (least sure first).
DROP VIEW IF EXISTS low_confidence_queue;
CREATE VIEW low_confidence_queue AS
SELECT review_id, product_id, review_date, rating, raw_label, sentiment_score, topic, review_text
FROM v_scored_reviews
WHERE status = 'low_confidence'
ORDER BY sentiment_score ASC, review_date DESC;

-- Reviews the AI could not score at all, with the reason (data-quality / model health signal).
DROP VIEW IF EXISTS failed_predictions;
CREATE VIEW failed_predictions AS
SELECT review_id, product_id, review_date, reason, review_text
FROM v_scored_reviews
WHERE status = 'failed';

-- Quality signal: star rating and predicted sentiment strongly disagree.
DROP VIEW IF EXISTS rating_sentiment_disagreement;
CREATE VIEW rating_sentiment_disagreement AS
SELECT review_id, product_id, review_date, rating, sentiment_label, sentiment_score, review_text
FROM v_scored_reviews
WHERE status = 'ok'
  AND ((rating >= 4 AND sentiment_label = 'negative')
    OR (rating <= 2 AND sentiment_label = 'positive'));
