-- =============================================================================
-- Batch 03: Type Downsizing on Season Accumulator Tables
-- Tables: player_batting_stats (2.3M), player_pitching_stats (0.9M),
--         player_fielding_stats (2.9M)
-- Risk: Low — season stats fit SMALLINT UNSIGNED (max 65535)
-- Downtime: Table rebuild per table (minutes each)
-- Estimated savings: ~114 MB
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PRE-FLIGHT: Verify no values exceed SMALLINT UNSIGNED (65535)
-- ─────────────────────────────────────────────────────────────────────────────

SELECT
  MAX(games) AS max_games,
  MAX(at_bats) AS max_ab,
  MAX(runs) AS max_runs,
  MAX(hits) AS max_hits,
  MAX(doubles_hit) AS max_doubles,
  MAX(triples) AS max_triples,
  MAX(home_runs) AS max_hr,
  MAX(rbi) AS max_rbi,
  MAX(walks) AS max_bb,
  MAX(strikeouts) AS max_so,
  MAX(stolen_bases) AS max_sb,
  MAX(caught_stealing) AS max_cs,
  MAX(inside_the_park_hr) AS max_itphr,
  COUNT(*) AS total_rows
FROM player_batting_stats;

SELECT
  MAX(games) AS max_g,
  MAX(games_started) AS max_gs,
  MAX(wins) AS max_w,
  MAX(losses) AS max_l,
  MAX(saves) AS max_sv,
  MAX(innings_pitched_outs) AS max_ipo,
  MAX(hits_allowed) AS max_ha,
  MAX(runs_allowed) AS max_ra,
  MAX(earned_runs) AS max_er,
  MAX(walks) AS max_bb,
  MAX(strikeouts) AS max_so,
  MAX(home_runs_allowed) AS max_hra,
  MAX(inside_the_park_hr_allowed) AS max_itphra,
  MAX(holds) AS max_hld,
  MAX(blown_saves) AS max_bs,
  MAX(quality_starts) AS max_qs,
  COUNT(*) AS total_rows
FROM player_pitching_stats;

SELECT
  MAX(games) AS max_g,
  MAX(innings) AS max_inn,
  MAX(putouts) AS max_po,
  MAX(assists) AS max_a,
  MAX(errors) AS max_e,
  COUNT(*) AS total_rows
FROM player_fielding_stats;

-- Record baseline sizes
SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('player_batting_stats', 'player_pitching_stats', 'player_fielding_stats');

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: player_batting_stats
-- 13 stat columns INT → SMALLINT UNSIGNED
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE player_batting_stats
  MODIFY `games` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `at_bats` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `runs` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `hits` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `doubles_hit` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `triples` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `home_runs` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `rbi` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `walks` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `strikeouts` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `stolen_bases` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `caught_stealing` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `inside_the_park_hr` smallint unsigned NOT NULL DEFAULT 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: player_pitching_stats
-- 17 stat columns INT → SMALLINT UNSIGNED
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE player_pitching_stats
  MODIFY `games` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `games_started` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `wins` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `losses` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `saves` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `innings_pitched_outs` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `hits_allowed` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `runs_allowed` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `earned_runs` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `walks` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `strikeouts` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `home_runs_allowed` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `inside_the_park_hr_allowed` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `holds` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `blown_saves` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `quality_starts` smallint unsigned NOT NULL DEFAULT 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: player_fielding_stats
-- 5 stat columns INT → SMALLINT UNSIGNED
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE player_fielding_stats
  MODIFY `games` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `innings` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `putouts` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `assists` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `errors` smallint unsigned NOT NULL DEFAULT 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- POST-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('player_batting_stats', 'player_pitching_stats', 'player_fielding_stats');

SELECT * FROM player_batting_stats ORDER BY id DESC LIMIT 5;
SELECT * FROM player_pitching_stats ORDER BY id DESC LIMIT 5;
SELECT * FROM player_fielding_stats ORDER BY id DESC LIMIT 5;

ANALYZE TABLE player_batting_stats;
ANALYZE TABLE player_pitching_stats;
ANALYZE TABLE player_fielding_stats;
