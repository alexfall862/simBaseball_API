-- 023: Add inside-the-park home run tracking columns
--
-- The engine now distinguishes "homerun" (over the fence) from
-- "inside_the_park_hr" in play-by-play Defensive Outcome.
-- These columns track ITPHR separately; the existing home_runs /
-- home_runs_allowed columns continue to count ALL home runs (both types).

-- Season accumulation tables
ALTER TABLE player_batting_stats
    ADD COLUMN inside_the_park_hr INT NOT NULL DEFAULT 0;

ALTER TABLE player_pitching_stats
    ADD COLUMN inside_the_park_hr_allowed INT NOT NULL DEFAULT 0;

-- Per-game box score tables
ALTER TABLE game_batting_lines
    ADD COLUMN inside_the_park_hr INT NOT NULL DEFAULT 0;

ALTER TABLE game_pitching_lines
    ADD COLUMN inside_the_park_hr_allowed INT NOT NULL DEFAULT 0;

-- Batting lab results
ALTER TABLE batting_lab_results
    ADD COLUMN inside_the_park_hr INT NOT NULL DEFAULT 0;
