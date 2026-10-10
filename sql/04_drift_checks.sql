-- Named queries used by src/drift.py.
-- Windows (relative to :as_of): current = last 7 days, baseline = the 28 days before that.

-- name: label_counts
SELECT product_id, win, label, COUNT(*) AS n, SUM(conf) AS conf_sum
FROM (
    SELECT c.product_id,
           p.sentiment_label  AS label,
           p.sentiment_score  AS conf,
           CASE WHEN c.review_date BETWEEN date(:as_of, '-6 days')  AND :as_of
                     THEN 'current'
                WHEN c.review_date BETWEEN date(:as_of, '-34 days') AND date(:as_of, '-7 days')
                     THEN 'baseline'
           END AS win
    FROM clean_reviews c
    JOIN review_predictions p ON p.review_id = c.review_id
    WHERE p.status IN ('ok', 'low_confidence')
)
WHERE win IS NOT NULL
GROUP BY product_id, win, label;

-- name: topic_counts
SELECT product_id, win, topic, COUNT(*) AS n
FROM (
    SELECT c.product_id,
           p.topic AS topic,
           CASE WHEN c.review_date BETWEEN date(:as_of, '-6 days')  AND :as_of
                     THEN 'current'
                WHEN c.review_date BETWEEN date(:as_of, '-34 days') AND date(:as_of, '-7 days')
                     THEN 'baseline'
           END AS win
    FROM clean_reviews c
    JOIN review_predictions p ON p.review_id = c.review_id
    WHERE p.status IN ('ok', 'low_confidence')
)
WHERE win IS NOT NULL
GROUP BY product_id, win, topic;

-- name: latest_date
SELECT MAX(c.review_date) AS d
FROM clean_reviews c
JOIN review_predictions p ON p.review_id = c.review_id
WHERE p.status <> 'failed';
