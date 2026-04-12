-- Engine expansion: batted ball types, contact quality, sac flies, GIDP,
-- batters faced, inherited runners, double plays.
--
-- All new columns use SMALLINT UNSIGNED (season accumulators) or
-- TINYINT UNSIGNED (per-game lines) to match existing conventions.

-- -----------------------------------------------------------------------
-- 1) Season accumulators
-- -----------------------------------------------------------------------

-- Batting: sacrifice_flies, gidp, ground/fly/popup, 7x contact types
ALTER TABLE player_batting_stats
    ADD COLUMN sacrifice_flies  SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER hbp,
    ADD COLUMN gidp             SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER sacrifice_flies,
    ADD COLUMN ground_balls     SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER gidp,
    ADD COLUMN fly_balls        SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER ground_balls,
    ADD COLUMN popups           SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER fly_balls,
    ADD COLUMN contact_barrel   SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER popups,
    ADD COLUMN contact_solid    SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_barrel,
    ADD COLUMN contact_flare    SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_solid,
    ADD COLUMN contact_burner   SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_flare,
    ADD COLUMN contact_under    SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_burner,
    ADD COLUMN contact_topped   SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_under,
    ADD COLUMN contact_weak     SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_topped;

-- Pitching: batters_faced, sacrifice_flies_allowed, gidp_induced,
--           ground/fly/popup allowed, inherited runners, 7x contact types
ALTER TABLE player_pitching_stats
    ADD COLUMN batters_faced            SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER wildpitches,
    ADD COLUMN sacrifice_flies_allowed  SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER batters_faced,
    ADD COLUMN gidp_induced             SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER sacrifice_flies_allowed,
    ADD COLUMN ground_balls_allowed     SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER gidp_induced,
    ADD COLUMN fly_balls_allowed        SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER ground_balls_allowed,
    ADD COLUMN popups_allowed           SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER fly_balls_allowed,
    ADD COLUMN inherited_runners        SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER popups_allowed,
    ADD COLUMN inherited_runners_scored SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER inherited_runners,
    ADD COLUMN contact_barrel           SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER inherited_runners_scored,
    ADD COLUMN contact_solid            SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_barrel,
    ADD COLUMN contact_flare            SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_solid,
    ADD COLUMN contact_burner           SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_flare,
    ADD COLUMN contact_under            SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_burner,
    ADD COLUMN contact_topped           SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_under,
    ADD COLUMN contact_weak             SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_topped;

-- Fielding: double_plays_turned
ALTER TABLE player_fielding_stats
    ADD COLUMN double_plays SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER errors;

-- -----------------------------------------------------------------------
-- 2) Per-game lines
-- -----------------------------------------------------------------------

ALTER TABLE game_batting_lines
    ADD COLUMN sacrifice_flies  TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER stamina_cost,
    ADD COLUMN gidp             TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER sacrifice_flies,
    ADD COLUMN ground_balls     TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER gidp,
    ADD COLUMN fly_balls        TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER ground_balls,
    ADD COLUMN popups           TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER fly_balls,
    ADD COLUMN contact_barrel   TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER popups,
    ADD COLUMN contact_solid    TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_barrel,
    ADD COLUMN contact_flare    TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_solid,
    ADD COLUMN contact_burner   TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_flare,
    ADD COLUMN contact_under    TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_burner,
    ADD COLUMN contact_topped   TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_under,
    ADD COLUMN contact_weak     TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_topped;

ALTER TABLE game_pitching_lines
    ADD COLUMN batters_faced            TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER stamina_cost,
    ADD COLUMN sacrifice_flies_allowed  TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER batters_faced,
    ADD COLUMN gidp_induced             TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER sacrifice_flies_allowed,
    ADD COLUMN ground_balls_allowed     TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER gidp_induced,
    ADD COLUMN fly_balls_allowed        TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER ground_balls_allowed,
    ADD COLUMN popups_allowed           TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER fly_balls_allowed,
    ADD COLUMN inherited_runners        TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER popups_allowed,
    ADD COLUMN inherited_runners_scored TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER inherited_runners,
    ADD COLUMN contact_barrel           TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER inherited_runners_scored,
    ADD COLUMN contact_solid            TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_barrel,
    ADD COLUMN contact_flare            TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_solid,
    ADD COLUMN contact_burner           TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_flare,
    ADD COLUMN contact_under            TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_burner,
    ADD COLUMN contact_topped           TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_under,
    ADD COLUMN contact_weak             TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER contact_topped;

ALTER TABLE game_fielding_lines
    ADD COLUMN double_plays TINYINT UNSIGNED NOT NULL DEFAULT 0 AFTER errors;
