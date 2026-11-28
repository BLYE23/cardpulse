-- CardPulse website metrics. All historical comparisons use v_as_of.as_of_date,
-- not the machine's current date. SQLite 3.25+ (window functions) required.
-- Recreate views in reverse dependency order, then create in dependency order.
DROP VIEW IF EXISTS v_set_value_series;
DROP VIEW IF EXISTS v_card_metrics;
DROP VIEW IF EXISTS v_card_history;
DROP VIEW IF EXISTS v_as_of;

-- Most recent TCGplayer observation date across the entire database.
CREATE VIEW v_as_of AS
SELECT MAX(price_date) AS as_of_date
FROM price_observations
WHERE market = 'tcgplayer';

-- Every USD price observation for a card's chosen primary printing.
CREATE VIEW v_card_history AS
SELECT c.card_id, p.price_date, p.price
FROM cards AS c
JOIN price_observations AS p
  ON p.card_id = c.card_id
 AND p.printing = c.primary_printing
 AND p.market = 'tcgplayer';

-- One row per card with a primary printing. USD prices are from TCGplayer;
-- EUR prices are from Cardmarket, converted using the latest FX rate.
CREATE VIEW v_card_metrics AS
WITH
latest_usd AS (
    SELECT card_id, price AS usd, price_date AS usd_date
    FROM (
        SELECT card_id, price, price_date,
               ROW_NUMBER() OVER (
                   PARTITION BY card_id ORDER BY price_date DESC
               ) AS rn
        FROM v_card_history
    )
    WHERE rn = 1
),
first_usd AS (
    SELECT card_id, MIN(price_date) AS first_date
    FROM v_card_history
    GROUP BY card_id
),
latest_eur AS (
    SELECT card_id, price AS eur, price_date AS eur_date
    FROM (
        SELECT p.card_id, p.price, p.price_date,
               ROW_NUMBER() OVER (
                   PARTITION BY p.card_id ORDER BY p.price_date DESC
               ) AS rn
        FROM price_observations AS p
        JOIN cards AS c
          ON c.card_id = p.card_id
         AND c.primary_printing = p.printing
        WHERE p.market = 'cardmarket'
    )
    WHERE rn = 1
),
latest_fx AS (
    SELECT rate AS fx_rate
    FROM fx_rates
    ORDER BY rate_date DESC
    LIMIT 1
),
window_12m AS (
    SELECT h.card_id,
           MIN(h.price) AS low_12m,
           MAX(h.price) AS high_12m,
           COUNT(*) AS points_12m
    FROM v_card_history AS h
    CROSS JOIN v_as_of AS a
    WHERE h.price_date >= date(a.as_of_date, '-12 months')
    GROUP BY h.card_id
),
base AS (
    SELECT
        c.card_id, c.name, c.set_id, c.local_id, c.rarity,
        c.hp, c.illustrator, c.category, c.dex_id, c.image_url,
        c.primary_printing,
        u.usd, u.usd_date, f.first_date,
        e.eur, e.eur_date,
        x.fx_rate,
        a.as_of_date,
        w.low_12m, w.high_12m, w.points_12m,
        -- For monthly changes, use the earliest observation on/after the
        -- first day of the target month. The first_date gate is applied below.
        (
            SELECT h.price FROM v_card_history AS h
            WHERE h.card_id = c.card_id
              AND h.price_date >= date(a.as_of_date, 'start of month', '-3 months')
            ORDER BY h.price_date ASC LIMIT 1
        ) AS old_3m,
        (
            SELECT h.price FROM v_card_history AS h
            WHERE h.card_id = c.card_id
              AND h.price_date >= date(a.as_of_date, 'start of month', '-12 months')
            ORDER BY h.price_date ASC LIMIT 1
        ) AS old_12m,
        -- 7-day change: latest observation at least 7 days before as_of_date,
        -- so one missed daily run does not blank the value. Looking back at most
        -- 14 days (CHG_7D_MAX_LOOKBACK_DAYS) keeps a monthly point from posing as a week.
        (
            SELECT h.price FROM v_card_history AS h
            WHERE h.card_id = c.card_id
              AND h.price_date <= date(a.as_of_date, '-7 days')
              AND h.price_date >= date(a.as_of_date, '-14 days')
            ORDER BY h.price_date DESC LIMIT 1
        ) AS old_7d
    FROM cards AS c
    CROSS JOIN v_as_of AS a
    LEFT JOIN latest_usd AS u ON u.card_id = c.card_id
    LEFT JOIN first_usd AS f ON f.card_id = c.card_id
    LEFT JOIN latest_eur AS e ON e.card_id = c.card_id
    LEFT JOIN latest_fx AS x ON 1 = 1
    LEFT JOIN window_12m AS w ON w.card_id = c.card_id
    WHERE c.primary_printing IS NOT NULL
),
calculated AS (
    SELECT b.*,
           ROUND(b.eur * b.fx_rate, 2) AS eu_usd,
           -- GAP_MIN_USD = 1.0; GAP_SAME_THRESHOLD = 0.10
           CASE
               WHEN b.usd IS NULL OR b.eur IS NULL OR b.fx_rate IS NULL
                    OR b.usd < 1.0 OR ROUND(b.eur * b.fx_rate, 2) < 1.0
                   THEN NULL
               WHEN ABS(1.0 - ROUND(b.eur * b.fx_rate, 2) / b.usd) < 0.10
                   THEN 0.0
               ELSE ROUND(1.0 - ROUND(b.eur * b.fx_rate, 2) / b.usd, 3)
           END AS gap,
           CASE
               WHEN b.first_date <= date(b.as_of_date, 'start of month', '-3 months', '+1 month', '-1 day')
                    AND b.old_3m > 0
                   THEN ROUND(b.usd / b.old_3m - 1.0, 4)
           END AS chg_3m,
           CASE
               WHEN b.first_date <= date(b.as_of_date, 'start of month', '-12 months', '+1 month', '-1 day')
                    AND b.old_12m > 0
                   THEN ROUND(b.usd / b.old_12m - 1.0, 4)
           END AS chg_12m,
           CASE WHEN b.old_7d > 0 THEN ROUND(b.usd / b.old_7d - 1.0, 4) END AS chg_7d,
           CASE
               WHEN b.points_12m >= 2 AND b.high_12m > b.low_12m
                   THEN ROUND((b.usd - b.low_12m) / (b.high_12m - b.low_12m), 3)
           END AS range_pos_12m
    FROM base AS b
)
SELECT
    card_id, name, set_id, local_id, rarity, hp, illustrator,
    category, dex_id, image_url, primary_printing,
    usd, usd_date, first_date, eur, eur_date, fx_rate, eu_usd,
    gap,
    CASE
        WHEN gap IS NULL THEN NULL
        WHEN gap = 0 THEN 'same'
        -- GAP_WILD_THRESHOLD = 0.50
        WHEN ABS(gap) > 0.50 THEN 'check_condition'
        WHEN gap > 0 THEN 'eu_cheaper'
        ELSE 'us_cheaper'
    END AS gap_label,
    chg_3m, chg_12m, chg_7d,
    low_12m, high_12m, range_pos_12m,
    CASE
        WHEN range_pos_12m IS NULL THEN NULL
        -- RANGE_LOW_POS = 0.20; RANGE_HIGH_POS = 0.80
        WHEN range_pos_12m <= 0.20 THEN 'low'
        WHEN range_pos_12m >= 0.80 THEN 'high'
        ELSE 'mid'
    END AS range_label_12m
FROM calculated;

-- Set value on each distinct history date. A card contributes only when it
-- has an observation on that date; no carry-forward of earlier prices.
CREATE VIEW v_set_value_series AS
WITH cards_per_set AS (
    SELECT set_id, COUNT(*) AS cards_in_set
    FROM cards
    WHERE primary_printing IS NOT NULL
    GROUP BY set_id
)
SELECT
    c.set_id,
    h.price_date,
    ROUND(SUM(h.price), 2) AS total_usd,
    COUNT(DISTINCT h.card_id) AS cards_priced,
    n.cards_in_set,
    ROUND(COUNT(DISTINCT h.card_id) * 1.0 / n.cards_in_set, 4) AS coverage
FROM v_card_history AS h
JOIN cards AS c ON c.card_id = h.card_id
JOIN cards_per_set AS n ON n.set_id = c.set_id
GROUP BY c.set_id, h.price_date
-- SET_VALUE_MIN_COVERAGE = 0.60
HAVING COUNT(DISTINCT h.card_id) * 1.0 / n.cards_in_set >= 0.60;
