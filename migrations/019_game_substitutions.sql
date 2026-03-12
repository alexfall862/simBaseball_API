-- 019_game_substitutions.sql
-- Per-game substitution tracking from the game engine.
-- Records pitching changes, emergency pitchers, and (future)
-- pinch hits and defensive substitutions.

CREATE TABLE IF NOT EXISTS game_substitutions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  game_id INT NOT NULL,
  league_year_id INT NOT NULL,
  inning INT NOT NULL DEFAULT 0,
  half VARCHAR(10) NOT NULL DEFAULT '',
  sub_type VARCHAR(30) NOT NULL DEFAULT '',
  player_in_id BIGINT UNSIGNED NOT NULL,
  player_out_id BIGINT UNSIGNED NOT NULL,
  new_position VARCHAR(5) NOT NULL DEFAULT '',
  KEY idx_gsub_game (game_id),
  KEY idx_gsub_lyid (league_year_id),
  KEY idx_gsub_player_in (player_in_id),
  KEY idx_gsub_player_out (player_out_id),
  KEY idx_gsub_type (sub_type, league_year_id),
  CONSTRAINT fk_gsub_game FOREIGN KEY (game_id) REFERENCES gamelist(id) ON DELETE CASCADE
) ENGINE=InnoDB;
