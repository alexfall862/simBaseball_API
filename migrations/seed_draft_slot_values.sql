-- draft_slot_values was empty on the live database, so every draft pick fell
-- back to the $60,000 default. Per-round values from
-- seeding/draft_slot_values_seed.py (whose ON DUPLICATE guard never fires on
-- the NULL pick_in_round rows, hence this idempotent form).
INSERT INTO draft_slot_values (round, pick_in_round, slot_value)
SELECT v.round, NULL, v.slot_value
FROM (
    SELECT 1 AS round, 5000000.00 AS slot_value UNION ALL
    SELECT 2, 2000000.00 UNION ALL SELECT 3, 1000000.00 UNION ALL
    SELECT 4, 750000.00 UNION ALL SELECT 5, 500000.00 UNION ALL
    SELECT 6, 400000.00 UNION ALL SELECT 7, 300000.00 UNION ALL
    SELECT 8, 250000.00 UNION ALL SELECT 9, 200000.00 UNION ALL
    SELECT 10, 175000.00 UNION ALL SELECT 11, 150000.00 UNION ALL
    SELECT 12, 130000.00 UNION ALL SELECT 13, 115000.00 UNION ALL
    SELECT 14, 100000.00 UNION ALL SELECT 15, 90000.00 UNION ALL
    SELECT 16, 80000.00 UNION ALL SELECT 17, 75000.00 UNION ALL
    SELECT 18, 70000.00 UNION ALL SELECT 19, 65000.00 UNION ALL
    SELECT 20, 60000.00
) v
WHERE NOT EXISTS (
    SELECT 1 FROM draft_slot_values d
    WHERE d.round = v.round AND d.pick_in_round IS NULL
);
