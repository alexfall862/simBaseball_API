--
-- Table structure for table `award_types`
-- Data-driven catalog of the trophies users vote for. Seeded by
-- migrations/add_awards_tables.sql and services/awards.ensure_awards_schema().
--

DROP TABLE IF EXISTS `award_types`;
CREATE TABLE `award_types` (
  `code`             varchar(40)  NOT NULL,
  `name`             varchar(80)  NOT NULL,
  `category`         varchar(20)  NOT NULL DEFAULT 'major',
  `ptype_scope`      varchar(10)  NOT NULL DEFAULT 'any',
  `has_league_split` tinyint      NOT NULL DEFAULT '1',
  `is_per_position`  tinyint      NOT NULL DEFAULT '0',
  `allows_multiple`  tinyint      NOT NULL DEFAULT '0',
  `sort_order`       int          NOT NULL DEFAULT '100',
  `description`      varchar(255) DEFAULT NULL,
  PRIMARY KEY (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
