-- Persist the seeded playoff field so later-round logic honors manual seeding
-- overrides instead of re-deriving seeds from win/loss records.
--
-- Needed primarily for MLB: _advance_mlb_round recomputes the field to find the
-- bye teams (seeds 1 & 2) when building the Division Series, because those two
-- seeds never appear in a Wild Card series row.  Without persistence, a manual
-- reseed in the admin editor would be honored in the WC round but silently
-- snap back to record-based seeds in the DS round.  CWS / conference / MiLB
-- already persist their seeds (cws_bracket, conf_tournament_field, the series
-- rows themselves), so this table is currently written only for level 9 — but
-- the schema is level-generic for future use.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS.  No backfill — _advance_mlb_round
-- falls back to determine_mlb_playoff_field when no rows exist, so brackets
-- created before this migration keep working.

CREATE TABLE IF NOT EXISTS `playoff_seeds` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_year_id` int NOT NULL,
  `league_level` int NOT NULL,
  `conference` varchar(50) NOT NULL DEFAULT '',
  `seed` int NOT NULL,
  `team_id` int NOT NULL,
  `qualifier` varchar(30) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_playoff_seeds` (`league_year_id`, `league_level`, `conference`, `seed`)
) ENGINE=InnoDB;
