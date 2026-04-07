-- =============================================================================
-- Batch 02: Type Downsizing on Per-Game Line Tables
-- Tables: game_batting_lines (2.3M), game_pitching_lines (0.9M),
--         game_fielding_lines (2.6M)
-- Risk: Low — verify MAX() values first
-- Downtime: Table rebuild per table (minutes each)
-- Estimated savings: ~178 MB (stat columns) + ~75 MB (id/player_id) = ~253 MB
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PRE-FLIGHT: Verify no values exceed new type limits
-- TINYINT UNSIGNED max = 255, SMALLINT UNSIGNED max = 65535
-- ─────────────────────────────────────────────────────────────────────────────

-- game_batting_lines: all stat columns must be <= 255
SELECT
  MAX(at_bats) AS max_at_bats,
  MAX(runs) AS max_runs,
  MAX(hits) AS max_hits,
  MAX(doubles_hit) AS max_doubles,
  MAX(triples) AS max_triples,
  MAX(home_runs) AS max_hr,
  MAX(rbi) AS max_rbi,
  MAX(walks) AS max_walks,
  MAX(strikeouts) AS max_so,
  MAX(stolen_bases) AS max_sb,
  MAX(caught_stealing) AS max_cs,
  MAX(plate_appearances) AS max_pa,
  MAX(hbp) AS max_hbp,
  MAX(inside_the_park_hr) AS max_itphr,
  MAX(stamina_cost) AS max_stamina,
  MAX(batting_order) AS max_bat_order,
  MAX(id) AS max_id,
  MAX(player_id) AS max_player_id,
  COUNT(*) AS total_rows
FROM game_batting_lines;

-- game_pitching_lines: most columns <= 255, pitches/balls/strikes/outs <= 65535
SELECT
  MAX(games_started) AS max_gs,
  MAX(win) AS max_w,
  MAX(loss) AS max_l,
  MAX(save_recorded) AS max_sv,
  MAX(hold) AS max_hld,
  MAX(blown_save) AS max_bs,
  MAX(quality_start) AS max_qs,
  MAX(innings_pitched_outs) AS max_ipo,
  MAX(hits_allowed) AS max_ha,
  MAX(runs_allowed) AS max_ra,
  MAX(earned_runs) AS max_er,
  MAX(walks) AS max_bb,
  MAX(strikeouts) AS max_so,
  MAX(home_runs_allowed) AS max_hra,
  MAX(pitches_thrown) AS max_pitches,
  MAX(balls) AS max_balls,
  MAX(strikes) AS max_strikes,
  MAX(hbp) AS max_hbp,
  MAX(wildpitches) AS max_wp,
  MAX(inside_the_park_hr_allowed) AS max_itphra,
  MAX(stamina_cost) AS max_stamina,
  MAX(pitch_appearance_order) AS max_pao,
  MAX(id) AS max_id,
  MAX(player_id) AS max_player_id,
  COUNT(*) AS total_rows
FROM game_pitching_lines;

-- game_fielding_lines: all stat columns must be <= 255
SELECT
  MAX(innings) AS max_inn,
  MAX(putouts) AS max_po,
  MAX(assists) AS max_a,
  MAX(errors) AS max_e,
  MAX(id) AS max_id,
  MAX(player_id) AS max_player_id,
  COUNT(*) AS total_rows
FROM game_fielding_lines;

-- Record baseline sizes
SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('game_batting_lines', 'game_pitching_lines', 'game_fielding_lines');

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: game_batting_lines
-- Changes: id BIGINT UNSIGNED → INT UNSIGNED
--          player_id BIGINT UNSIGNED → INT
--          batting_order SMALLINT → TINYINT UNSIGNED
--          14 stat columns INT → TINYINT UNSIGNED
--          stamina_cost INT → TINYINT UNSIGNED (nullable)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE game_batting_lines
  MODIFY `id` int unsigned NOT NULL AUTO_INCREMENT,
  MODIFY `player_id` int NOT NULL,
  MODIFY `batting_order` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `at_bats` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `runs` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `hits` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `doubles_hit` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `triples` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `home_runs` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `rbi` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `walks` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `strikeouts` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `stolen_bases` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `caught_stealing` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `plate_appearances` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `hbp` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `inside_the_park_hr` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `stamina_cost` tinyint unsigned DEFAULT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: game_pitching_lines
-- Changes: id BIGINT UNSIGNED → INT UNSIGNED
--          player_id BIGINT UNSIGNED → INT
--          pitch_appearance_order SMALLINT → TINYINT UNSIGNED
--          innings_pitched_outs, pitches_thrown, balls, strikes → SMALLINT UNSIGNED
--          All other stat columns INT → TINYINT UNSIGNED
--          stamina_cost INT → TINYINT UNSIGNED (nullable)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE game_pitching_lines
  MODIFY `id` int unsigned NOT NULL AUTO_INCREMENT,
  MODIFY `player_id` int NOT NULL,
  MODIFY `pitch_appearance_order` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `games_started` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `win` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `loss` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `save_recorded` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `hold` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `blown_save` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `quality_start` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `innings_pitched_outs` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `hits_allowed` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `runs_allowed` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `earned_runs` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `walks` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `strikeouts` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `home_runs_allowed` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `pitches_thrown` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `balls` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `strikes` smallint unsigned NOT NULL DEFAULT 0,
  MODIFY `hbp` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `wildpitches` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `inside_the_park_hr_allowed` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `stamina_cost` tinyint unsigned DEFAULT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: game_fielding_lines
-- Changes: id BIGINT UNSIGNED → INT UNSIGNED
--          player_id BIGINT UNSIGNED → INT
--          4 stat columns INT → TINYINT UNSIGNED
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE game_fielding_lines
  MODIFY `id` int unsigned NOT NULL AUTO_INCREMENT,
  MODIFY `player_id` int NOT NULL,
  MODIFY `innings` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `putouts` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `assists` tinyint unsigned NOT NULL DEFAULT 0,
  MODIFY `errors` tinyint unsigned NOT NULL DEFAULT 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- POST-FLIGHT: Verify row counts and size reduction
-- ─────────────────────────────────────────────────────────────────────────────

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('game_batting_lines', 'game_pitching_lines', 'game_fielding_lines');

-- Spot-check latest rows
SELECT * FROM game_batting_lines ORDER BY id DESC LIMIT 5;
SELECT * FROM game_pitching_lines ORDER BY id DESC LIMIT 5;
SELECT * FROM game_fielding_lines ORDER BY id DESC LIMIT 5;

-- Update optimizer statistics
ANALYZE TABLE game_batting_lines;
ANALYZE TABLE game_pitching_lines;
ANALYZE TABLE game_fielding_lines;
