-- Migration 043: Performance indexes for season simulation throughput
--
-- Adds covering/composite indexes on tables hit most frequently during
-- build_week_payloads() and weekly processing.  All are additive — no
-- columns or data are modified.

-- -----------------------------------------------------------------------
-- gamelist: the primary game lookup is (season, season_week, league_level).
-- Currently has no composite index covering all three.
-- -----------------------------------------------------------------------
ALTER TABLE gamelist
  ADD KEY idx_gl_season_week_level (season, season_week, league_level);

-- -----------------------------------------------------------------------
-- player_fatigue_state: global recovery UPDATE filters on
--   league_year_id AND stamina < 100
-- -----------------------------------------------------------------------
ALTER TABLE player_fatigue_state
  ADD KEY idx_pfs_ly_stamina (league_year_id, stamina);

-- -----------------------------------------------------------------------
-- game_batting_lines: re-sim rollback aggregates by (league_year, game).
-- Existing idx_gbl_game covers (game_id) alone but not (ly, game).
-- -----------------------------------------------------------------------
ALTER TABLE game_batting_lines
  ADD KEY idx_gbl_ly_game (league_year_id, game_id);

-- -----------------------------------------------------------------------
-- game_pitching_lines: same access pattern as batting lines.
-- -----------------------------------------------------------------------
ALTER TABLE game_pitching_lines
  ADD KEY idx_gpl_ly_game (league_year_id, game_id);

-- -----------------------------------------------------------------------
-- game_fielding_lines: same access pattern.
-- -----------------------------------------------------------------------
ALTER TABLE game_fielding_lines
  ADD KEY idx_gfl_ly_game (league_year_id, game_id);

-- -----------------------------------------------------------------------
-- player_injury_events: _tick_injuries() decrements weeks_remaining
-- via JOIN on player_injury_state and filters weeks_remaining > 0.
-- Career-eligible check also filters by injury_type_id.
-- -----------------------------------------------------------------------
ALTER TABLE player_injury_events
  ADD KEY idx_pie_weeks_type (weeks_remaining, injury_type_id);

-- -----------------------------------------------------------------------
-- engine_diagnostic_log: queried by (ly, week, subweek, level) for
-- UPDATE after storing results.  Existing idx covers (ly, week, subweek)
-- but not level.
-- -----------------------------------------------------------------------
ALTER TABLE engine_diagnostic_log
  ADD KEY idx_edl_full (league_year_id, season_week, subweek, league_level);
