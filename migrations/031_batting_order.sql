-- Migration 031: Add batting_order to per-game batting lines
--
-- The engine now returns batting_order (1-9) per batter.
-- Substitutes inherit the slot of the player they replaced,
-- so all batters with plate appearances have a valid 1-9 value.

ALTER TABLE game_batting_lines
  ADD COLUMN batting_order SMALLINT NOT NULL DEFAULT 0 AFTER position_code;
