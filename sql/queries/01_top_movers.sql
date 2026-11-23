-- Which 10 cards gained the most over 12 months (current price >= $5)?
SELECT
    m.card_id,
    m.name AS card_name,
    s.name AS set_name,
    m.rarity,
    m.usd,
    m.chg_12m
FROM v_card_metrics AS m
JOIN sets AS s ON s.set_id = m.set_id
WHERE m.usd >= 5.0
  AND m.chg_12m IS NOT NULL
ORDER BY m.chg_12m DESC, m.usd DESC, m.card_id
LIMIT 10;
