--
-- Table structure for table `player_awards`
-- Durable, cross-season record of player trophies + All-Star selections.
-- See migrations/add_awards_tables.sql and services/awards.py.
--

DROP TABLE IF EXISTS `player_awards`;
CREATE TABLE `player_awards` (
  `id`             bigint          NOT NULL AUTO_INCREMENT,
  `player_id`      bigint unsigned NOT NULL,
  `league_year_id` int             NOT NULL,
  `league_level`   int             NOT NULL DEFAULT '9',
  `award_code`     varchar(40)     NOT NULL,
  `sub_league`     varchar(10)     NOT NULL DEFAULT '',
  `position_code`  varchar(10)     NOT NULL DEFAULT '',
  `team_id`        int             DEFAULT NULL,
  `rank`           tinyint         NOT NULL DEFAULT '1',
  `is_winner`      tinyint         NOT NULL DEFAULT '1',
  `vote_points`    decimal(10,2)   DEFAULT NULL,
  `vote_share`     decimal(5,4)    DEFAULT NULL,
  `metadata_json`  json            DEFAULT NULL,
  `created_by`     varchar(80)     DEFAULT NULL,
  `created_at`     datetime        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_award_slot` (`league_year_id`,`league_level`,`award_code`,`sub_league`,`position_code`,`player_id`),
  KEY `idx_player` (`player_id`),
  KEY `idx_season` (`league_year_id`,`league_level`),
  KEY `idx_award` (`award_code`),
  CONSTRAINT `fk_pa_award_type` FOREIGN KEY (`award_code`) REFERENCES `award_types` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
