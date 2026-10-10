-- Input : TEMP TABLE stg_valid  (rows that passed Python-side validation/normalisation;
--         columns: raw_id, review_id, product_id, user_id, rating, review_text,
--                  review_date, text_hash, source_file, batch_id)
-- Output: upserts into clean_reviews, writes every dropped row to rejected_reviews.

-- 1. Several raw rows with the same review_id -> keep the latest raw row, reject the rest.
DROP TABLE IF EXISTS temp.stg_ranked;
CREATE TEMP TABLE stg_ranked AS
SELECT s.*,
       ROW_NUMBER() OVER (PARTITION BY review_id ORDER BY raw_id DESC) AS rn
FROM stg_valid s;

INSERT INTO rejected_reviews (raw_id, review_id, product_id, user_id, rating, review_text,
                              review_date, source_file, batch_id, reject_reason, rejected_at)
SELECT raw_id, review_id, product_id, user_id, rating, review_text, review_date,
       source_file, batch_id, 'duplicate_review_id', datetime('now')
FROM stg_ranked WHERE rn > 1;

-- 2. Same review_id already in clean_reviews with identical content -> nothing to do (re-delivery).
DROP TABLE IF EXISTS temp.stg_new;
CREATE TEMP TABLE stg_new AS
SELECT r.*, COALESCE(NULLIF(r.user_id, ''), r.review_id) AS uid
FROM stg_ranked r
WHERE r.rn = 1
  AND NOT EXISTS (SELECT 1 FROM clean_reviews c
                  WHERE c.review_id = r.review_id
                    AND c.text_hash = r.text_hash
                    AND c.rating IS r.rating
                    AND c.review_date = r.review_date);

INSERT INTO rejected_reviews (raw_id, review_id, product_id, user_id, rating, review_text,
                              review_date, source_file, batch_id, reject_reason, rejected_at)
SELECT raw_id, review_id, product_id, user_id, rating, review_text, review_date,
       source_file, batch_id, 'duplicate_review_id', datetime('now')
FROM stg_ranked r
WHERE r.rn = 1 AND r.raw_id NOT IN (SELECT raw_id FROM stg_new);

-- 3. Near-duplicates: different review_id but same text + user + product
--    (inside this load, or already present in clean_reviews).
DROP TABLE IF EXISTS temp.stg_flagged;
CREATE TEMP TABLE stg_flagged AS
SELECT n.*,
       ROW_NUMBER() OVER (PARTITION BY text_hash, product_id, uid ORDER BY review_id) AS dup_rn,
       EXISTS (SELECT 1 FROM clean_reviews c
               WHERE c.text_hash = n.text_hash
                 AND c.product_id = n.product_id
                 AND COALESCE(NULLIF(c.user_id, ''), c.review_id) = n.uid
                 AND c.review_id <> n.review_id) AS dup_in_clean
FROM stg_new n;

INSERT INTO rejected_reviews (raw_id, review_id, product_id, user_id, rating, review_text,
                              review_date, source_file, batch_id, reject_reason, rejected_at)
SELECT raw_id, review_id, product_id, user_id, rating, review_text, review_date,
       source_file, batch_id, 'near_duplicate', datetime('now')
FROM stg_flagged WHERE dup_rn > 1 OR dup_in_clean = 1;

-- 4. Changed reviews invalidate their old AI prediction (it will be recomputed).
DELETE FROM review_predictions
WHERE review_id IN (SELECT f.review_id FROM stg_flagged f
                    JOIN clean_reviews c ON c.review_id = f.review_id
                    WHERE f.dup_rn = 1 AND f.dup_in_clean = 0);

-- 5. Upsert survivors: new review_id -> insert, existing review_id with new content -> update.
INSERT INTO clean_reviews (review_id, product_id, user_id, rating, review_text,
                           review_date, text_hash, batch_id, updated_at)
SELECT review_id, product_id, user_id, rating, review_text, review_date, text_hash,
       batch_id, datetime('now')
FROM stg_flagged
WHERE dup_rn = 1 AND dup_in_clean = 0
ON CONFLICT (review_id) DO UPDATE SET
    product_id  = excluded.product_id,
    user_id     = excluded.user_id,
    rating      = excluded.rating,
    review_text = excluded.review_text,
    review_date = excluded.review_date,
    text_hash   = excluded.text_hash,
    batch_id    = excluded.batch_id,
    updated_at  = excluded.updated_at;
