-- Postseason accumulation tables.
--
-- Playoff games (gamelist.game_type = 'playoff') accumulate into these clones
-- instead of player_batting_stats / player_pitching_stats /
-- player_fielding_stats, so regular-season leaderboards are never polluted by
-- postseason games.  Same columns, same keys (player_id, league_year_id,
-- team_id [+ position_code]).  Per-game line tables (game_batting_lines,
-- game_pitching_lines, game_fielding_lines) are shared by every game type.
--
-- Idempotent.  The API also bootstraps these lazily on the first playoff game
-- via services.stat_accumulator.ensure_playoff_stat_tables -- keep in sync.

CREATE TABLE IF NOT EXISTS `player_batting_stats_playoff`  LIKE `player_batting_stats`;
CREATE TABLE IF NOT EXISTS `player_pitching_stats_playoff` LIKE `player_pitching_stats`;
CREATE TABLE IF NOT EXISTS `player_fielding_stats_playoff` LIKE `player_fielding_stats`;
