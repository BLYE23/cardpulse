-- CardPulse data-quality checks. Each block must return its failing rows.
-- The marker format is parsed by pipeline/validate.py; do not change it.

-- check: cards_without_set | error
SELECT c.*
FROM cards AS c
LEFT JOIN sets AS s ON s.set_id = c.set_id
WHERE s.set_id IS NULL;

-- check: price_unknown_printing | error
SELECT p.*
FROM price_observations AS p
LEFT JOIN card_printings AS cp
  ON cp.card_id = p.card_id AND cp.printing = p.printing
WHERE cp.card_id IS NULL;

-- check: price_non_positive | error
SELECT *
FROM price_observations
WHERE price IS NULL OR price <= 0;

-- check: price_future_date | error
SELECT *
FROM price_observations
WHERE price_date > date('now', '+1 day');

-- check: price_currency_mismatch | error
SELECT *
FROM price_observations
WHERE (market = 'tcgplayer' AND currency <> 'USD')
   OR (market = 'cardmarket' AND currency <> 'EUR');

-- check: fx_missing | error
SELECT 'fx_rates is empty' AS issue
WHERE NOT EXISTS (SELECT 1 FROM fx_rates);

-- check: primary_without_price | error
SELECT c.card_id, c.primary_printing
FROM cards AS c
WHERE c.primary_printing IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM price_observations AS p
      WHERE p.card_id = c.card_id
        AND p.printing = c.primary_printing
        AND p.market = 'tcgplayer'
  );

-- check: pokemon_card_without_dex | warn
SELECT card_id, name
FROM cards
WHERE category = 'Pokemon' AND dex_id IS NULL;

-- check: card_without_tcgplayer | warn
SELECT card_id, name
FROM cards
WHERE primary_printing IS NULL;

-- check: price_jump_10x | warn
WITH ordered_prices AS (
    SELECT card_id, price_date, price,
           LAG(price) OVER (
               PARTITION BY card_id ORDER BY price_date
           ) AS previous_price
    FROM v_card_history
)
SELECT card_id, price_date, price, previous_price
FROM ordered_prices
WHERE previous_price IS NOT NULL
  AND (price > previous_price * 10.0 OR previous_price > price * 10.0);

-- check: history_too_short | warn
SELECT card_id, COUNT(*) AS history_points
FROM v_card_history
GROUP BY card_id
HAVING COUNT(*) < 2;

-- check: prices_stale | warn
SELECT as_of_date
FROM v_as_of
WHERE as_of_date < date('now', '-3 days');
