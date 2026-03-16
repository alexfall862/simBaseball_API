-- Migration 032: Add pitch_appearance_order to per-game pitching lines
--
-- The engine now returns pitch_appearance_order (1=starter, 2=first reliever, etc.)
-- per pitcher. This allows the boxscore to display pitchers in the order
-- they actually appeared in the game.

ALTER TABLE game_pitching_lines
  ADD COLUMN pitch_appearance_order SMALLINT NOT NULL DEFAULT 0 AFTER team_id;
