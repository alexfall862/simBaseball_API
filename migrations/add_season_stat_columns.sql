-- Promote per-game-only counting stats into season accumulator tables.
--
-- These fields are already tracked in game_batting_lines / game_pitching_lines
-- but were never accumulated into the season-level tables, forcing derived
-- stats (OBP, BF, K%, BB%) to use approximations.
--
-- Run order:
--   1) This file  (add columns)
--   2) backfill_season_stats_from_game_lines.sql  (populate from history)

-- -----------------------------------------------------------------------
-- Batting: plate_appearances, hbp
-- -----------------------------------------------------------------------
ALTER TABLE player_batting_stats
    ADD COLUMN plate_appearances SMALLINT UNSIGNED NOT NULL DEFAULT 0
        AFTER caught_stealing,
    ADD COLUMN hbp SMALLINT UNSIGNED NOT NULL DEFAULT 0
        AFTER plate_appearances;

-- -----------------------------------------------------------------------
-- Pitching: pitches_thrown, balls, strikes, hbp, wildpitches
-- -----------------------------------------------------------------------
ALTER TABLE player_pitching_stats
    ADD COLUMN pitches_thrown SMALLINT UNSIGNED NOT NULL DEFAULT 0
        AFTER inside_the_park_hr_allowed,
    ADD COLUMN balls SMALLINT UNSIGNED NOT NULL DEFAULT 0
        AFTER pitches_thrown,
    ADD COLUMN strikes SMALLINT UNSIGNED NOT NULL DEFAULT 0
        AFTER balls,
    ADD COLUMN hbp SMALLINT UNSIGNED NOT NULL DEFAULT 0
        AFTER strikes,
    ADD COLUMN wildpitches SMALLINT UNSIGNED NOT NULL DEFAULT 0
        AFTER hbp;
