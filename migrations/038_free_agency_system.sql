-- Migration 038: Free agency auction, market pricing, and player demands
--
-- Adds tables for:
-- 1. fa_market_history   - historical $/WAR tracking from completed signings
-- 2. fa_auction          - one row per FA player entering the auction pool
-- 3. fa_auction_offers   - per-org offers on active auctions
-- 4. player_demands      - cached WAR-based demand calculations
-- 5. ALTER transaction_log to add new enum values

-- ── 1. Market history ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `fa_market_history` (
  `id`              INT NOT NULL AUTO_INCREMENT,
  `player_id`       INT NOT NULL,
  `league_year_id`  INT NOT NULL,
  `war_at_signing`  DECIMAL(6,2) NOT NULL,
  `total_value`     DECIMAL(18,2) NOT NULL,
  `aav`             DECIMAL(18,2) NOT NULL,
  `years`           INT NOT NULL,
  `bonus`           DECIMAL(18,2) NOT NULL DEFAULT 0,
  `age_at_signing`  INT NOT NULL,
  `service_years`   INT NOT NULL,
  `contract_id`     INT NOT NULL,
  `source`          ENUM('fa_auction','direct_signing','extension','arb_renewal') NOT NULL,
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_mh_year`     (`league_year_id`),
  KEY `idx_mh_war`      (`war_at_signing`),
  KEY `idx_mh_player`   (`player_id`),
  KEY `idx_mh_contract` (`contract_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 2. Auction pool ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `fa_auction` (
  `id`                INT NOT NULL AUTO_INCREMENT,
  `player_id`         INT NOT NULL,
  `league_year_id`    INT NOT NULL,
  `phase`             ENUM('open','listening','finalize','completed','withdrawn') NOT NULL DEFAULT 'open',
  `phase_started_week` INT NOT NULL,
  `entered_week`      INT NOT NULL,
  `min_total_value`   DECIMAL(18,2) NOT NULL,
  `min_aav`           DECIMAL(18,2) NOT NULL,
  `min_years`         INT NOT NULL DEFAULT 1,
  `max_years`         INT NOT NULL DEFAULT 5,
  `war_at_entry`      DECIMAL(6,2) NOT NULL,
  `age_at_entry`      INT NOT NULL,
  `service_years`     INT NOT NULL,
  `winning_offer_id`  INT DEFAULT NULL,
  `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_auction_player_year` (`player_id`, `league_year_id`),
  KEY `idx_auction_phase` (`phase`),
  KEY `idx_auction_ly`    (`league_year_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 3. Auction offers ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `fa_auction_offers` (
  `id`                INT NOT NULL AUTO_INCREMENT,
  `auction_id`        INT NOT NULL,
  `org_id`            INT NOT NULL,
  `years`             INT NOT NULL,
  `bonus`             DECIMAL(18,2) NOT NULL DEFAULT 0,
  `total_value`       DECIMAL(18,2) NOT NULL,
  `aav`               DECIMAL(18,2) NOT NULL,
  `salaries_json`     JSON NOT NULL,
  `level_id`          INT NOT NULL,
  `submitted_week`    INT NOT NULL,
  `last_updated_week` INT NOT NULL,
  `status`            ENUM('active','outbid','withdrawn','won','lost') NOT NULL DEFAULT 'active',
  `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_offer_auction_org` (`auction_id`, `org_id`),
  KEY `idx_offer_org` (`org_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 4. Player demands ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `player_demands` (
  `id`              INT NOT NULL AUTO_INCREMENT,
  `player_id`       INT NOT NULL,
  `league_year_id`  INT NOT NULL,
  `demand_type`     ENUM('fa','extension','buyout') NOT NULL,
  `war_snapshot`    DECIMAL(6,2) NOT NULL,
  `age_snapshot`    INT NOT NULL,
  `service_years`   INT NOT NULL,
  `min_years`       INT DEFAULT NULL,
  `max_years`       INT DEFAULT NULL,
  `min_aav`         DECIMAL(18,2) DEFAULT NULL,
  `min_total_value` DECIMAL(18,2) DEFAULT NULL,
  `buyout_price`    DECIMAL(18,2) DEFAULT NULL,
  `dollar_per_war`  DECIMAL(18,2) NOT NULL,
  `computed_at`     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_demand_player_year_type` (`player_id`, `league_year_id`, `demand_type`),
  KEY `idx_demand_player` (`player_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 5. Extend transaction_log enum ──────────────────────────────────

ALTER TABLE `transaction_log`
  MODIFY COLUMN `transaction_type` ENUM(
    'trade','release','signing','extension','buyout',
    'promote','demote','ir_place','ir_activate','renewal',
    'draft_sign','draft_pick_trade',
    'fa_offer','fa_offer_update','fa_auction_sign','arb_renewal'
  ) NOT NULL;
