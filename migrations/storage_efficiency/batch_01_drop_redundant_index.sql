-- =============================================================================
-- Batch 01: Drop Redundant Index on player_fatigue_state
-- Risk: Zero — index is 100% redundant with PRIMARY KEY
-- Downtime: None (instant metadata operation)
-- =============================================================================

-- PRE-FLIGHT: Confirm the redundant index exists
SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'player_fatigue_state'
  AND INDEX_NAME = 'idx_fatigue_player_year';

-- The PRIMARY KEY is (player_id, league_year_id).
-- idx_fatigue_player_year is (player_id, league_year_id) — identical, fully redundant.

ALTER TABLE player_fatigue_state DROP INDEX idx_fatigue_player_year;

-- POST-FLIGHT: Verify only PK and idx_pfs_ly_stamina remain
SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'player_fatigue_state'
ORDER BY INDEX_NAME, SEQ_IN_INDEX;
