-- Migration 014: Add batting order preferences to defense assignments
--
-- Consolidates lineup configuration into team_position_plan so each
-- defensive assignment carries its own batting order preferences.
-- Previously these lived in the separate team_lineup_roles table.

ALTER TABLE team_position_plan
  ADD COLUMN lineup_role VARCHAR(20) NOT NULL DEFAULT 'balanced',
  ADD COLUMN min_order SMALLINT NULL DEFAULT NULL,
  ADD COLUMN max_order SMALLINT NULL DEFAULT NULL;

ALTER TABLE team_position_plan
  ADD CONSTRAINT chk_lineup_role CHECK (lineup_role IN ('table_setter','on_base','slugger','balanced','speed','bottom')),
  ADD CONSTRAINT chk_min_order CHECK (min_order IS NULL OR (min_order >= 1 AND min_order <= 9)),
  ADD CONSTRAINT chk_max_order CHECK (max_order IS NULL OR (max_order >= 1 AND max_order <= 9)),
  ADD CONSTRAINT chk_order_range CHECK (min_order IS NULL OR max_order IS NULL OR min_order <= max_order);
