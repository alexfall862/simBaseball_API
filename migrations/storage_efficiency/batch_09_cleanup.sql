-- =============================================================================
-- Batch 09: Low-Impact Cleanup
-- Tables: forenames, surnames, player_position_usage_week, gamelist
-- Risk: Negligible
-- Estimated savings: ~8 MB
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PRE-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

SELECT MAX(weight) AS max_weight, MAX(CHAR_LENGTH(name)) AS max_name_len,
       MAX(CHAR_LENGTH(region)) AS max_region_len, COUNT(*) AS row_count
FROM forenames;

SELECT MAX(weight) AS max_weight, MAX(CHAR_LENGTH(name)) AS max_name_len,
       MAX(CHAR_LENGTH(region)) AS max_region_len, COUNT(*) AS row_count
FROM surnames;

SELECT MAX(starts_this_week) AS max_starts, COUNT(*) AS row_count
FROM player_position_usage_week;

-- Check if random_seed values fit in INT UNSIGNED (max 4,294,967,295)
-- or if they use the full BIGINT range
SELECT MAX(random_seed) AS max_seed, MIN(random_seed) AS min_seed
FROM gamelist;

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('forenames', 'surnames', 'player_position_usage_week', 'gamelist');

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: Name pool tables
-- weight: kept as INT (max value ~105M exceeds SMALLINT/MEDIUMINT range)
-- name: VARCHAR(100) → VARCHAR(50) (temp table allocation improvement)
-- region: VARCHAR(100) → VARCHAR(40) (temp table allocation improvement)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE forenames
  MODIFY `name` varchar(50) NOT NULL,
  MODIFY `region` varchar(40) NOT NULL;

ALTER TABLE surnames
  MODIFY `name` varchar(50) NOT NULL,
  MODIFY `region` varchar(40) NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: player_position_usage_week
-- starts_this_week: INT → TINYINT UNSIGNED (max 4 starts/week)
-- Saves 3 bytes/row × 2.5M rows = ~7.2 MB
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE player_position_usage_week
  MODIFY `starts_this_week` tinyint unsigned NOT NULL DEFAULT 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: gamelist.random_seed
-- ONLY run this if the PRE-FLIGHT shows max_seed <= 4294967295 AND min_seed >= 0.
-- If seeds are negative or exceed INT UNSIGNED range, SKIP this change.
-- ─────────────────────────────────────────────────────────────────────────────

-- UNCOMMENT the line below ONLY if pre-flight confirms values fit:
-- ALTER TABLE gamelist MODIFY `random_seed` int unsigned DEFAULT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- POST-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('forenames', 'surnames', 'player_position_usage_week', 'gamelist');

SELECT * FROM forenames ORDER BY id DESC LIMIT 5;
SELECT * FROM surnames ORDER BY id DESC LIMIT 5;
SELECT * FROM player_position_usage_week ORDER BY id DESC LIMIT 5;

ANALYZE TABLE forenames;
ANALYZE TABLE surnames;
ANALYZE TABLE player_position_usage_week;
