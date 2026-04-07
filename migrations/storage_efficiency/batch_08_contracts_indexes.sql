-- =============================================================================
-- Batch 08: Contract DECIMAL Right-Sizing + game_results Index Improvements
-- Risk: Low
-- Downtime: Table rebuilds (small-medium tables)
-- Estimated savings: ~2 MB + improved query performance
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PRE-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

-- Verify max salary fits in DECIMAL(12,2) (max $9,999,999,999.99)
SELECT MAX(salary) AS max_salary, MIN(salary) AS min_salary, COUNT(*) AS row_count
FROM contractDetails;

SELECT MAX(bonus) AS max_bonus, MIN(bonus) AS min_bonus, COUNT(*) AS row_count
FROM contracts;

-- Record baseline sizes
SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('contractDetails', 'contracts', 'game_results');

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: DECIMAL right-sizing
-- contractDetails.salary: DECIMAL(20,2) → DECIMAL(12,2) saves 4 bytes/row
-- contracts.bonus: DECIMAL(20,2) → DECIMAL(12,2) saves 4 bytes/row
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE contractDetails
  MODIFY `salary` decimal(12,2) NOT NULL;

ALTER TABLE contracts
  MODIFY `bonus` decimal(12,2) NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: game_results composite indexes
-- Replace single-column team indexes with team+season composites.
-- The new indexes cover both FK lookups (team_id leading) and
-- the common query pattern: WHERE season = :s AND team_id = :t.
--
-- NOTE: We must keep indexes that back FK constraints. MySQL requires
-- an index with the FK column as a prefix. The new composite indexes
-- satisfy this requirement since team_id is the leading column.
-- ─────────────────────────────────────────────────────────────────────────────

-- Add new composite indexes (these replace the old single-column FK indexes;
-- MySQL auto-drops the old fk_game_results_team_home / fk_game_results_team_away
-- indexes once the composites satisfy the FK backing requirement)
CREATE INDEX idx_gr_home_season ON game_results(home_team_id, season);
CREATE INDEX idx_gr_away_season ON game_results(away_team_id, season);

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: play_by_play_json LONGTEXT → MEDIUMTEXT
-- LONGTEXT allows 4GB/row; MEDIUMTEXT allows 16MB/row (more than sufficient)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE game_results
  MODIFY `play_by_play_json` mediumtext DEFAULT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- POST-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('contractDetails', 'contracts', 'game_results');

-- Verify new indexes exist and old ones are gone
SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'game_results'
ORDER BY INDEX_NAME, SEQ_IN_INDEX;

SELECT * FROM contractDetails ORDER BY id DESC LIMIT 5;
SELECT * FROM contracts ORDER BY id DESC LIMIT 5;

ANALYZE TABLE contractDetails;
ANALYZE TABLE contracts;
ANALYZE TABLE game_results;
