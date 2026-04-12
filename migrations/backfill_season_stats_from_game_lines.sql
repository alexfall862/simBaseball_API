-- Backfill newly-added season accumulator columns from existing per-game lines.
--
-- Prerequisites: add_season_stat_columns.sql must be run first.
--
-- For very large tables, run each UPDATE in a separate transaction or batch
-- by league_year_id to avoid long locks.

-- -----------------------------------------------------------------------
-- Batting: plate_appearances, hbp
-- -----------------------------------------------------------------------
UPDATE player_batting_stats bs
JOIN (
    SELECT player_id, league_year_id, team_id,
           SUM(plate_appearances) AS pa,
           SUM(hbp)               AS hbp
    FROM game_batting_lines
    GROUP BY player_id, league_year_id, team_id
) gl ON gl.player_id      = bs.player_id
    AND gl.league_year_id  = bs.league_year_id
    AND gl.team_id         = bs.team_id
SET bs.plate_appearances = gl.pa,
    bs.hbp               = gl.hbp;

-- -----------------------------------------------------------------------
-- Pitching: pitches_thrown, balls, strikes, hbp, wildpitches
-- -----------------------------------------------------------------------
UPDATE player_pitching_stats ps
JOIN (
    SELECT player_id, league_year_id, team_id,
           SUM(pitches_thrown) AS pitches_thrown,
           SUM(balls)         AS balls,
           SUM(strikes)       AS strikes,
           SUM(hbp)           AS hbp,
           SUM(wildpitches)   AS wildpitches
    FROM game_pitching_lines
    GROUP BY player_id, league_year_id, team_id
) gl ON gl.player_id      = ps.player_id
    AND gl.league_year_id  = ps.league_year_id
    AND gl.team_id         = ps.team_id
SET ps.pitches_thrown = gl.pitches_thrown,
    ps.balls          = gl.balls,
    ps.strikes        = gl.strikes,
    ps.hbp            = gl.hbp,
    ps.wildpitches    = gl.wildpitches;
