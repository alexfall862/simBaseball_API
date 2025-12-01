-- ============================================================================
-- Database Performance Optimization Indexes
-- simBaseball API - Game Payload Endpoint Optimization
-- ============================================================================
--
-- This file contains CREATE INDEX statements to optimize the game payload
-- endpoint and related queries. Run these against your MySQL database.
--
-- IMPORTANT: Run these during low-traffic periods as they may lock tables.
-- Check existing indexes first to avoid duplicates:
--   SHOW INDEX FROM table_name;
--
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROTATION & PITCHER QUERIES
-- Used by: services/rotation.py
-- ----------------------------------------------------------------------------

-- Optimize rotation lookups by team
CREATE INDEX IF NOT EXISTS idx_rotation_team
ON team_pitching_rotation(team_id);

-- Optimize rotation slot lookups
CREATE INDEX IF NOT EXISTS idx_rotation_slots_rotation
ON team_pitching_rotation_slots(rotation_id, slot);

-- Optimize rotation state lookups
CREATE INDEX IF NOT EXISTS idx_rotation_state_team
ON team_rotation_state(team_id);

-- ----------------------------------------------------------------------------
-- POSITION PLAN & LINEUP QUERIES
-- Used by: services/lineups.py
-- ----------------------------------------------------------------------------

-- Optimize position plan lookups (bulk query optimization)
-- This is critical for the bulk loader: _load_all_position_plans_for_team
CREATE INDEX IF NOT EXISTS idx_position_plan_team_lookup
ON team_position_plan(team_id, position_code, vs_hand, priority);

-- Optimize lineup roles lookups
CREATE INDEX IF NOT EXISTS idx_lineup_roles_team
ON team_lineup_roles(team_id, slot);

-- Optimize weekly usage lookups (bulk query optimization)
-- This is critical for: _load_all_weekly_usage_for_team
CREATE INDEX IF NOT EXISTS idx_usage_week_lookup
ON player_position_usage_week(league_year_id, season_week, team_id, position_code, vs_hand);

-- Alternative composite index if the above is too large
-- CREATE INDEX IF NOT EXISTS idx_usage_week_team_pos
-- ON player_position_usage_week(team_id, league_year_id, season_week, position_code);

-- ----------------------------------------------------------------------------
-- PLAYER STRATEGY QUERIES
-- Used by: services/rotation.py, services/game_payload.py
-- ----------------------------------------------------------------------------

-- Optimize strategy lookups (supports bulk loading)
CREATE INDEX IF NOT EXISTS idx_strategies_player
ON playerStrategies(playerID, orgID);

-- ----------------------------------------------------------------------------
-- STAMINA & FATIGUE QUERIES
-- Used by: services/stamina.py
-- ----------------------------------------------------------------------------

-- Optimize stamina lookups (already has composite PK but adding for clarity)
-- If player_fatigue_state doesn't have this as PK, add it:
CREATE INDEX IF NOT EXISTS idx_fatigue_player_year
ON player_fatigue_state(player_id, league_year_id);

-- Optimize bulk stamina lookups
CREATE INDEX IF NOT EXISTS idx_fatigue_year_players
ON player_fatigue_state(league_year_id, player_id);

-- ----------------------------------------------------------------------------
-- INJURY QUERIES
-- Used by: services/injuries.py
-- ----------------------------------------------------------------------------

-- Optimize injury state lookups
CREATE INDEX IF NOT EXISTS idx_injury_state_player
ON player_injury_state(player_id, status);

-- Optimize injury event lookups
CREATE INDEX IF NOT EXISTS idx_injury_events_id
ON player_injury_events(id);

-- Optimize career injury lookups (bulk query)
CREATE INDEX IF NOT EXISTS idx_career_injuries_player
ON career_injuries(player_id);

-- ----------------------------------------------------------------------------
-- DEFENSIVE XP QUERIES
-- Used by: services/defense_xp.py
-- ----------------------------------------------------------------------------

-- Optimize position experience lookups (bulk query)
CREATE INDEX IF NOT EXISTS idx_position_xp_player
ON player_position_experience(player_id, position_code);

-- Optimize defense XP config lookups
CREATE INDEX IF NOT EXISTS idx_defense_xp_config_level
ON defense_xp_config(league_level, position_code);

-- ----------------------------------------------------------------------------
-- ROSTER & CONTRACT QUERIES
-- Used by: rosters/__init__.py, services/game_payload.py
-- ----------------------------------------------------------------------------

-- Optimize the complex 6-table join for roster queries
-- These support: _get_team_roster_player_ids, _get_team_pitcher_ids

-- Contracts table
CREATE INDEX IF NOT EXISTS idx_contracts_active_lookup
ON contracts(isActive, playerID, current_level);

-- Contract team shares (critical for roster joins)
CREATE INDEX IF NOT EXISTS idx_shares_holder_org
ON contractTeamShare(isHolder, contractDetailsID, orgID);

-- Contract details
CREATE INDEX IF NOT EXISTS idx_contract_details_contract
ON contractDetails(contractID, id);

-- Teams table (for the outerjoin in roster queries)
CREATE INDEX IF NOT EXISTS idx_teams_org_level
ON teams(orgID, team_level, id);

-- Players table - pitch_hand lookup
CREATE INDEX IF NOT EXISTS idx_players_pitch_hand
ON simbbPlayers(id, pitch_hand);

-- ----------------------------------------------------------------------------
-- GAME & SEASON QUERIES
-- Used by: services/game_payload.py
-- ----------------------------------------------------------------------------

-- Optimize gamelist lookups
CREATE INDEX IF NOT EXISTS idx_gamelist_id
ON gamelist(id);

-- Optimize season lookups for league_year resolution
CREATE INDEX IF NOT EXISTS idx_seasons_id_year
ON seasons(id, year);

-- Optimize league_year lookups
CREATE INDEX IF NOT EXISTS idx_league_years_year
ON league_years(league_year, id);

-- Optimize level_rules lookups
CREATE INDEX IF NOT EXISTS idx_level_rules_league
ON level_rules(league_level);

-- Optimize level_sim_config lookups
CREATE INDEX IF NOT EXISTS idx_level_sim_config_league
ON level_sim_config(league_level);

-- ----------------------------------------------------------------------------
-- GAME WEEKS QUERIES
-- Used by: financials/books.py, simulations/fake_season.py
-- ----------------------------------------------------------------------------

-- Optimize game week lookups
CREATE INDEX IF NOT EXISTS idx_game_weeks_year_week
ON game_weeks(league_year_id, week_index);

-- ============================================================================
-- POST-INDEX OPTIMIZATION COMMANDS
-- ============================================================================
--
-- After creating indexes, run these commands to update statistics:
--
-- ANALYZE TABLE team_pitching_rotation;
-- ANALYZE TABLE team_pitching_rotation_slots;
-- ANALYZE TABLE team_rotation_state;
-- ANALYZE TABLE team_position_plan;
-- ANALYZE TABLE team_lineup_roles;
-- ANALYZE TABLE player_position_usage_week;
-- ANALYZE TABLE playerStrategies;
-- ANALYZE TABLE player_fatigue_state;
-- ANALYZE TABLE player_injury_state;
-- ANALYZE TABLE player_injury_events;
-- ANALYZE TABLE career_injuries;
-- ANALYZE TABLE player_position_experience;
-- ANALYZE TABLE defense_xp_config;
-- ANALYZE TABLE contracts;
-- ANALYZE TABLE contractTeamShare;
-- ANALYZE TABLE contractDetails;
-- ANALYZE TABLE teams;
-- ANALYZE TABLE simbbPlayers;
-- ANALYZE TABLE gamelist;
-- ANALYZE TABLE seasons;
-- ANALYZE TABLE league_years;
-- ANALYZE TABLE level_rules;
-- ANALYZE TABLE level_sim_config;
-- ANALYZE TABLE game_weeks;
--
-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
--
-- To verify indexes were created successfully:
--
-- SHOW INDEX FROM team_pitching_rotation;
-- SHOW INDEX FROM team_position_plan;
-- SHOW INDEX FROM player_position_usage_week;
-- SHOW INDEX FROM playerStrategies;
-- SHOW INDEX FROM player_fatigue_state;
-- SHOW INDEX FROM contracts;
-- SHOW INDEX FROM contractTeamShare;
--
-- To check index usage in queries:
--
-- EXPLAIN SELECT * FROM team_position_plan WHERE team_id = 1;
-- EXPLAIN SELECT * FROM playerStrategies WHERE playerID IN (1,2,3,4,5);
--
-- ============================================================================
