-- Migration 018: Add is_conference flag to gamelist
-- Distinguishes conference games from OOC for college standings

ALTER TABLE gamelist
  ADD COLUMN is_conference TINYINT(1) NOT NULL DEFAULT 0
  AFTER random_seed;

-- Back-fill existing college games: mark all as conference (legacy schedules
-- did not separate OOC / conference by week, so default to conference).
UPDATE gamelist SET is_conference = 1 WHERE league_level = 3;

-- Index for efficient conference-record queries
CREATE INDEX idx_gamelist_conference ON gamelist (is_conference, league_level);
