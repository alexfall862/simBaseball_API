-- 017_game_stats_boxscores.sql
-- Per-game player stat lines + boxscore/play-by-play storage
-- Supports box score reconstruction and game logs

-- 1. Per-game batting lines
CREATE TABLE IF NOT EXISTS game_batting_lines (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  game_id INT NOT NULL,
  player_id BIGINT UNSIGNED NOT NULL,
  team_id INT NOT NULL,
  league_year_id INT NOT NULL,
  at_bats INT NOT NULL DEFAULT 0,
  runs INT NOT NULL DEFAULT 0,
  hits INT NOT NULL DEFAULT 0,
  doubles_hit INT NOT NULL DEFAULT 0,
  triples INT NOT NULL DEFAULT 0,
  home_runs INT NOT NULL DEFAULT 0,
  rbi INT NOT NULL DEFAULT 0,
  walks INT NOT NULL DEFAULT 0,
  strikeouts INT NOT NULL DEFAULT 0,
  stolen_bases INT NOT NULL DEFAULT 0,
  caught_stealing INT NOT NULL DEFAULT 0,
  UNIQUE KEY uq_game_batting (game_id, player_id),
  KEY idx_gbl_player (player_id, league_year_id),
  KEY idx_gbl_game (game_id),
  KEY idx_gbl_team (team_id, league_year_id),
  CONSTRAINT fk_gbl_game FOREIGN KEY (game_id) REFERENCES gamelist(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 2. Per-game pitching lines
CREATE TABLE IF NOT EXISTS game_pitching_lines (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  game_id INT NOT NULL,
  player_id BIGINT UNSIGNED NOT NULL,
  team_id INT NOT NULL,
  league_year_id INT NOT NULL,
  games_started INT NOT NULL DEFAULT 0,
  win INT NOT NULL DEFAULT 0,
  loss INT NOT NULL DEFAULT 0,
  save_recorded INT NOT NULL DEFAULT 0,
  innings_pitched_outs INT NOT NULL DEFAULT 0,
  hits_allowed INT NOT NULL DEFAULT 0,
  runs_allowed INT NOT NULL DEFAULT 0,
  earned_runs INT NOT NULL DEFAULT 0,
  walks INT NOT NULL DEFAULT 0,
  strikeouts INT NOT NULL DEFAULT 0,
  home_runs_allowed INT NOT NULL DEFAULT 0,
  UNIQUE KEY uq_game_pitching (game_id, player_id),
  KEY idx_gpl_player (player_id, league_year_id),
  KEY idx_gpl_game (game_id),
  KEY idx_gpl_team (team_id, league_year_id),
  CONSTRAINT fk_gpl_game FOREIGN KEY (game_id) REFERENCES gamelist(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 3. Add boxscore and play-by-play columns to game_results
ALTER TABLE game_results
  ADD COLUMN IF NOT EXISTS boxscore_json JSON DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS play_by_play_json LONGTEXT DEFAULT NULL;
