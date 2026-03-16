-- Migration 033: Pitcher decisions (hold/blown_save/quality_start) and
--                substitution entry-state context
--
-- The engine now tracks holds, blown saves, and quality starts per pitcher,
-- and provides entry-state context on each pitching change substitution.

-- 1. New pitching decision columns on per-game lines
ALTER TABLE game_pitching_lines
  ADD COLUMN hold INT NOT NULL DEFAULT 0 AFTER save_recorded,
  ADD COLUMN blown_save INT NOT NULL DEFAULT 0 AFTER hold,
  ADD COLUMN quality_start INT NOT NULL DEFAULT 0 AFTER blown_save;

-- 2. New pitching decision columns on season accumulation
ALTER TABLE player_pitching_stats
  ADD COLUMN holds INT NOT NULL DEFAULT 0,
  ADD COLUMN blown_saves INT NOT NULL DEFAULT 0,
  ADD COLUMN quality_starts INT NOT NULL DEFAULT 0;

-- 3. Substitution entry-state context
ALTER TABLE game_substitutions
  ADD COLUMN entry_score_diff INT DEFAULT NULL,
  ADD COLUMN entry_runners_on INT DEFAULT NULL,
  ADD COLUMN entry_inning INT DEFAULT NULL,
  ADD COLUMN entry_outs INT DEFAULT NULL,
  ADD COLUMN entry_is_save_situation TINYINT(1) DEFAULT NULL;
