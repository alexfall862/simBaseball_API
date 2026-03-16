-- Migration 035: Widen player_fielding_stats.position_code from VARCHAR(3) to VARCHAR(16)
--
-- The engine can return position codes like "startingpitcher" in the fielding
-- stats. While the API normalizes most of these, some edge cases (e.g., DH
-- fielding entries, emergency pitcher labels) can exceed 3 characters.

ALTER TABLE player_fielding_stats
  MODIFY COLUMN position_code VARCHAR(16) NOT NULL;
