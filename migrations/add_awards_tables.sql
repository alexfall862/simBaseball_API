-- Awards system: durable, cross-season record of player trophies + All-Star selections.
--
-- award_types  : data-driven reference of the trophies users vote for (MVP, Cy Young, ...).
-- player_awards : one row per (player, season, award slot). Persists across seasons so a
--                 player can accumulate awards over a career. Issued for MLB (level 9) today;
--                 league_level is carried so MiLB can be enabled later without a schema change.
--
-- NOTE: sub_league and position_code default to '' (empty), NOT NULL. MySQL treats NULLs as
-- distinct in unique keys, which would defeat the uniqueness guard below. Empty-string sentinels
-- keep uq_award_slot enforceable for non-split / non-positional awards.

-- ---------------------------------------------------------------------------
-- Reference: the set of awards that exist
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `award_types` (
  `code`             varchar(40)  NOT NULL,
  `name`             varchar(80)  NOT NULL,
  `category`         varchar(20)  NOT NULL DEFAULT 'major',   -- major | batting | pitching | fielding | selection
  `ptype_scope`      varchar(10)  NOT NULL DEFAULT 'any',     -- any | hitter | pitcher
  `has_league_split` tinyint      NOT NULL DEFAULT 1,         -- 1 => AL/NL winners; 0 => one league-wide winner
  `is_per_position`  tinyint      NOT NULL DEFAULT 0,         -- 1 => one winner per fielding position (SS/gold glove, etc.)
  `allows_multiple`  tinyint      NOT NULL DEFAULT 0,         -- 1 => many recipients per league (All-Star selections)
  `sort_order`       int          NOT NULL DEFAULT 100,
  `description`      varchar(255) DEFAULT NULL,
  PRIMARY KEY (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------------
-- Durable per-player award record
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `player_awards` (
  `id`             bigint        NOT NULL AUTO_INCREMENT,
  `player_id`      bigint unsigned NOT NULL,
  `league_year_id` int           NOT NULL,
  `league_level`   int           NOT NULL DEFAULT 9,
  `award_code`     varchar(40)   NOT NULL,
  `sub_league`     varchar(10)   NOT NULL DEFAULT '',         -- 'AL' / 'NL' / '' (no split)
  `position_code`  varchar(10)   NOT NULL DEFAULT '',         -- 'SS','1B',... for per-position awards; '' otherwise
  `team_id`        int           DEFAULT NULL,                -- snapshot of player's team when awarded
  `rank`           tinyint       NOT NULL DEFAULT 1,          -- 1 = winner; >1 = finalist/runner-up
  `is_winner`      tinyint       NOT NULL DEFAULT 1,
  `vote_points`    decimal(10,2) DEFAULT NULL,                -- optional tally detail
  `vote_share`     decimal(5,4)  DEFAULT NULL,                -- optional 0..1 share of the vote
  `metadata_json`  json          DEFAULT NULL,
  `created_by`     varchar(80)   DEFAULT NULL,                -- admin/commissioner who entered it
  `created_at`     datetime      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  -- One row per player per award slot per season (prevents accidental double-entry).
  UNIQUE KEY `uq_award_slot` (`league_year_id`,`league_level`,`award_code`,`sub_league`,`position_code`,`player_id`),
  KEY `idx_player` (`player_id`),
  KEY `idx_season` (`league_year_id`,`league_level`),
  KEY `idx_award` (`award_code`),
  CONSTRAINT `fk_pa_award_type` FOREIGN KEY (`award_code`) REFERENCES `award_types` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---------------------------------------------------------------------------
-- Seed the standard MLB trophy set (idempotent)
-- ---------------------------------------------------------------------------
INSERT INTO `award_types`
    (`code`,`name`,`category`,`ptype_scope`,`has_league_split`,`is_per_position`,`allows_multiple`,`sort_order`,`description`)
VALUES
    ('mvp',             'Most Valuable Player',  'major',     'any',     1, 0, 0, 10,  'Most valuable player in each league.'),
    ('cy_young',        'Cy Young Award',        'pitching',  'pitcher', 1, 0, 0, 20,  'Best pitcher in each league.'),
    ('roy',             'Rookie of the Year',    'major',     'any',     1, 0, 0, 30,  'Best first-year player in each league.'),
    ('reliever',        'Reliever of the Year',  'pitching',  'pitcher', 1, 0, 0, 40,  'Best relief pitcher in each league.'),
    ('comeback',        'Comeback Player',       'major',     'any',     1, 0, 0, 50,  'Comeback Player of the Year in each league.'),
    ('silver_slugger',  'Silver Slugger',        'batting',   'hitter',  1, 1, 0, 60,  'Best offensive player at each position in each league.'),
    ('gold_glove',      'Gold Glove',            'fielding',  'any',     1, 1, 0, 70,  'Best defender at each position in each league.'),
    ('all_star',        'All-Star Selection',    'selection', 'any',     1, 0, 1, 90,  'Selected to the league All-Star roster.')
ON DUPLICATE KEY UPDATE
    `name`=VALUES(`name`), `category`=VALUES(`category`), `ptype_scope`=VALUES(`ptype_scope`),
    `has_league_split`=VALUES(`has_league_split`), `is_per_position`=VALUES(`is_per_position`),
    `allows_multiple`=VALUES(`allows_multiple`), `sort_order`=VALUES(`sort_order`),
    `description`=VALUES(`description`);
