-- Which rarities have the highest TCGplayer prices? Show count and
-- median-free MIN/AVG/MAX summary of each rarity's current USD price.
SELECT
    COALESCE(rarity, 'Unknown') AS rarity,
    COUNT(*) AS card_count,
    ROUND(MIN(usd), 2) AS min_usd,
    ROUND(AVG(usd), 2) AS avg_usd,
    ROUND(MAX(usd), 2) AS max_usd
FROM v_card_metrics
WHERE usd IS NOT NULL
GROUP BY COALESCE(rarity, 'Unknown')
ORDER BY AVG(usd) DESC, card_count DESC;
