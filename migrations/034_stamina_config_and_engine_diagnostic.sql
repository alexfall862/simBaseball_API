-- Migration 034: Add stamina recovery config to level_game_config
--                and engine diagnostic tracking table
--
-- 1. Stamina recovery is currently hardcoded at 5 per subweek with
--    durability multipliers. Move to per-level configurable values.
--
-- 2. Engine diagnostic table tracks games sent vs results received
--    to help diagnose missing game results.

-- 1. Stamina recovery columns on level_game_config
--    Separate base rates for pitchers vs position players.
ALTER TABLE level_game_config
  ADD COLUMN stamina_recovery_per_subweek DECIMAL(5,2) NOT NULL DEFAULT 5.0,
  ADD COLUMN stamina_recovery_pitcher_per_subweek DECIMAL(5,2) NOT NULL DEFAULT 5.0,
  ADD COLUMN durability_mult_iron_man DECIMAL(4,2) NOT NULL DEFAULT 1.50,
  ADD COLUMN durability_mult_dependable DECIMAL(4,2) NOT NULL DEFAULT 1.25,
  ADD COLUMN durability_mult_normal DECIMAL(4,2) NOT NULL DEFAULT 1.00,
  ADD COLUMN durability_mult_undependable DECIMAL(4,2) NOT NULL DEFAULT 0.75,
  ADD COLUMN durability_mult_tires_easily DECIMAL(4,2) NOT NULL DEFAULT 0.50;

-- 2. Engine diagnostic log
CREATE TABLE IF NOT EXISTS engine_diagnostic_log (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  league_year_id INT NOT NULL,
  season_week INT NOT NULL,
  subweek CHAR(1) NOT NULL,
  league_level INT DEFAULT NULL,
  games_sent INT NOT NULL DEFAULT 0,
  results_received INT NOT NULL DEFAULT 0,
  results_stored INT NOT NULL DEFAULT 0,
  missing_game_ids JSON DEFAULT NULL,
  error_message TEXT DEFAULT NULL,
  engine_response_ms INT DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_edl_week (league_year_id, season_week, subweek)
) ENGINE=InnoDB;
