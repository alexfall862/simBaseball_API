-- Migration 030: Add expanded boxscore fields to per-game line tables
--
-- Batting: position played, plate appearances, HBP
-- Pitching: pitch count, balls/strikes, HBP, wild pitches
--
-- These fields are already returned by the game engine but were not
-- previously captured in the per-game tables.

-- 1. Batting line expansions
ALTER TABLE game_batting_lines
  ADD COLUMN position_code VARCHAR(4) DEFAULT NULL AFTER team_id,
  ADD COLUMN plate_appearances INT NOT NULL DEFAULT 0 AFTER caught_stealing,
  ADD COLUMN hbp INT NOT NULL DEFAULT 0 AFTER plate_appearances;

-- 2. Pitching line expansions
ALTER TABLE game_pitching_lines
  ADD COLUMN pitches_thrown INT NOT NULL DEFAULT 0 AFTER home_runs_allowed,
  ADD COLUMN balls INT NOT NULL DEFAULT 0 AFTER pitches_thrown,
  ADD COLUMN strikes INT NOT NULL DEFAULT 0 AFTER balls,
  ADD COLUMN hbp INT NOT NULL DEFAULT 0 AFTER strikes,
  ADD COLUMN wildpitches INT NOT NULL DEFAULT 0 AFTER hbp;
