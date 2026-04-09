-- Add index on player_listed_position(league_year_id) to speed up
-- _load_listed_positions_batch in attribute_visibility.py which queries
-- WHERE league_year_id = :lyid on every roster/scouting request.
--
-- Existing indexes:
--   PRIMARY KEY (id)
--   UNIQUE (player_id, team_id, league_year_id)
--   KEY idx_plp_team_year (team_id, league_year_id)
--
-- None has league_year_id as a leading column, causing full table scans
-- when filtering by league_year_id alone.

CREATE INDEX idx_plp_league_year ON player_listed_position(league_year_id);
