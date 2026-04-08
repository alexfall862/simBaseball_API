-- Conference tournament support: widen playoff_series.conference and add field tracking table

-- 1. Widen conference column from VARCHAR(5) to VARCHAR(50) to hold full conference names
ALTER TABLE `playoff_series` MODIFY `conference` VARCHAR(50) DEFAULT NULL;

-- 2. Conference tournament field: tracks all qualified teams, seeds, and bye status
CREATE TABLE `conf_tournament_field` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_year_id` int NOT NULL,
  `conference` varchar(50) NOT NULL,
  `team_id` int NOT NULL,
  `seed` int NOT NULL,
  `has_bye` tinyint NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ct_field` (`league_year_id`, `conference`, `team_id`)
) ENGINE=InnoDB;
