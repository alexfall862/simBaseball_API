-- =============================================================================
-- Batch 04: player_fatigue_state Type Fixes
-- Risk: Low — small table (active players only)
-- Downtime: Near-instant rebuild
-- Savings: ~19 bytes/row + enables FK constraints
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PRE-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

SELECT
  MAX(player_id) AS max_player_id,
  MAX(league_year_id) AS max_ly_id,
  MAX(last_game_id) AS max_game_id,
  MAX(last_week_id) AS max_week_id,
  MAX(stamina) AS max_stamina,
  MIN(stamina) AS min_stamina,
  COUNT(*) AS total_rows
FROM player_fatigue_state;

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'player_fatigue_state';

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION
-- player_id: BIGINT UNSIGNED → INT (matches simbbPlayers.id)
-- league_year_id: BIGINT UNSIGNED → INT UNSIGNED (matches league_years.id)
-- last_game_id: BIGINT UNSIGNED → INT (matches gamelist.id)
-- last_week_id: BIGINT UNSIGNED → INT (matches game_weeks.id)
-- stamina: INT → TINYINT UNSIGNED (0-100 range)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE player_fatigue_state
  MODIFY `player_id` int NOT NULL,
  MODIFY `league_year_id` int unsigned NOT NULL,
  MODIFY `last_game_id` int DEFAULT NULL,
  MODIFY `last_week_id` int DEFAULT NULL,
  MODIFY `stamina` tinyint unsigned NOT NULL DEFAULT 100;

-- ─────────────────────────────────────────────────────────────────────────────
-- POST-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'player_fatigue_state';

SELECT * FROM player_fatigue_state ORDER BY last_updated_at DESC LIMIT 5;

ANALYZE TABLE player_fatigue_state;
