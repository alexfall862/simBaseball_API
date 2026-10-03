-- Per-level playoff rules that persist across seasons.
--
-- ws_home_field: how the World Series (level 9) picks its home team (team_a,
-- which hosts games 1, 2, 6 and 7):
--   'seed'    - better seed number, AL on a tie (original behavior, default)
--   'allstar' - champion of the league (AL/NL) that won this league year's
--               completed All-Star Game; falls back to 'seed' if there is no
--               completed All-Star result or it was a tie.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS.  No row = defaults, so code works
-- before this migration is applied (it falls back to 'seed').

CREATE TABLE IF NOT EXISTS `playoff_settings` (
  `league_level` int NOT NULL,
  `ws_home_field` varchar(16) NOT NULL DEFAULT 'seed',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`league_level`)
) ENGINE=InnoDB;
