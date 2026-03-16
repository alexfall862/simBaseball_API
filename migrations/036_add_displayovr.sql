-- Migration 036: Add displayovr column to simbbPlayers
--
-- Stores the computed 20-80 overall rating derived from the active
-- weight profile. Recomputed when a profile is activated.

ALTER TABLE simbbPlayers
  ADD COLUMN displayovr VARCHAR(4) DEFAULT NULL;
