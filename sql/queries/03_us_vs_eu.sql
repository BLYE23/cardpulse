-- For each set, how many cards are cheaper in Europe versus the US,
-- and what is the average relative price gap in each category?
SELECT
    m.set_id,
    s.name AS set_name,
    COALESCE(m.gap_label, 'unavailable') AS gap_label,
    COUNT(*) AS card_count,
    ROUND(AVG(m.gap), 3) AS avg_gap
FROM v_card_metrics AS m
JOIN sets AS s ON s.set_id = m.set_id
GROUP BY m.set_id, s.name, COALESCE(m.gap_label, 'unavailable')
ORDER BY s.name, gap_label;
