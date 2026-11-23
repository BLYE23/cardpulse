-- What is the latest estimated value of each set, and how has it changed
-- since the first date with sufficient price coverage?
WITH ranked AS (
    SELECT
        v.set_id,
        v.price_date,
        v.total_usd,
        v.cards_priced,
        v.cards_in_set,
        v.coverage,
        FIRST_VALUE(v.price_date) OVER (
            PARTITION BY v.set_id ORDER BY v.price_date ASC
        ) AS first_date,
        FIRST_VALUE(v.total_usd) OVER (
            PARTITION BY v.set_id ORDER BY v.price_date ASC
        ) AS first_total_usd,
        ROW_NUMBER() OVER (
            PARTITION BY v.set_id ORDER BY v.price_date DESC
        ) AS latest_rank
    FROM v_set_value_series AS v
)
SELECT
    r.set_id,
    s.name AS set_name,
    r.price_date AS latest_date,
    r.total_usd AS latest_total_usd,
    r.first_date,
    r.first_total_usd,
    ROUND(r.total_usd / NULLIF(r.first_total_usd, 0) - 1.0, 4) AS change_since_first,
    r.cards_priced,
    r.cards_in_set,
    r.coverage
FROM ranked AS r
JOIN sets AS s ON s.set_id = r.set_id
WHERE r.latest_rank = 1
ORDER BY r.total_usd DESC, r.set_id;
