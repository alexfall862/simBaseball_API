-- Migration 041: International Free Agent (IFA) Signing Period
--
-- Adds tables for:
-- 1. ifa_state          - window lifecycle per league year (pending/active/complete)
-- 2. ifa_bonus_pools    - per-org bonus pool allocation (inverse standings)
-- 3. ifa_auction        - per-player auction tracking (3-phase: open/listening/finalize)
-- 4. ifa_auction_offers - per-org bids on IFA players
-- 5. ifa_config         - configurable parameters (slot values, pool sizing, etc.)
-- 6. ALTER transaction_log to add ifa_offer, ifa_offer_update, ifa_signing

-- ── 1. IFA window state ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `ifa_state` (
  `id`              INT NOT NULL AUTO_INCREMENT,
  `league_year_id`  INT NOT NULL,
  `current_week`    INT NOT NULL DEFAULT 0,
  `total_weeks`     INT NOT NULL DEFAULT 20,
  `status`          ENUM('pending','active','complete') NOT NULL DEFAULT 'pending',
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ifa_state_ly` (`league_year_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 2. Bonus pools ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `ifa_bonus_pools` (
  `id`              INT NOT NULL AUTO_INCREMENT,
  `league_year_id`  INT NOT NULL,
  `org_id`          INT NOT NULL,
  `total_pool`      DECIMAL(18,2) NOT NULL,
  `spent`           DECIMAL(18,2) NOT NULL DEFAULT 0,
  `standing_rank`   INT NOT NULL,
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ifa_pool_org_year` (`league_year_id`, `org_id`),
  KEY `idx_ifa_pool_org` (`org_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 3. Per-player auctions ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `ifa_auction` (
  `id`                  INT NOT NULL AUTO_INCREMENT,
  `player_id`           INT NOT NULL,
  `league_year_id`      INT NOT NULL,
  `phase`               ENUM('open','listening','finalize','completed','withdrawn','expired') NOT NULL DEFAULT 'open',
  `phase_started_week`  INT NOT NULL,
  `entered_week`        INT NOT NULL,
  `slot_value`          DECIMAL(18,2) NOT NULL,
  `star_rating`         TINYINT NOT NULL,
  `age_at_entry`        INT NOT NULL,
  `winning_offer_id`    INT DEFAULT NULL,
  `created_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ifa_auction_player_year` (`player_id`, `league_year_id`),
  KEY `idx_ifa_auction_phase` (`phase`),
  KEY `idx_ifa_auction_ly` (`league_year_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 4. Auction offers ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `ifa_auction_offers` (
  `id`                INT NOT NULL AUTO_INCREMENT,
  `auction_id`        INT NOT NULL,
  `org_id`            INT NOT NULL,
  `bonus`             DECIMAL(18,2) NOT NULL,
  `submitted_week`    INT NOT NULL,
  `last_updated_week` INT NOT NULL,
  `status`            ENUM('active','outbid','withdrawn','won','lost') NOT NULL DEFAULT 'active',
  `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ifa_offer_auction_org` (`auction_id`, `org_id`),
  KEY `idx_ifa_offer_org` (`org_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 5. Config ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS `ifa_config` (
  `config_key`    VARCHAR(64) NOT NULL,
  `config_value`  VARCHAR(255) NOT NULL,
  PRIMARY KEY (`config_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO ifa_config (config_key, config_value) VALUES
  ('ifa_weeks',             '20'),
  ('phase_duration_weeks',  '3'),
  ('min_age',               '16'),
  ('slot_5star',            '5000000'),
  ('slot_4star',            '2500000'),
  ('slot_3star',            '1000000'),
  ('slot_2star',            '300000'),
  ('slot_1star',            '100000'),
  ('base_pool_amount',      '5000000'),
  ('pool_spread_factor',    '1.5'),
  ('ifa_contract_years',    '5'),
  ('ifa_target_level',      '4'),
  ('ifa_salary_per_year',   '40000');

-- ── 6. Extend transaction_log enum ──────────────────────────────────────

ALTER TABLE `transaction_log`
  MODIFY COLUMN `transaction_type`
    ENUM('trade','release','signing','extension','buyout',
         'promote','demote','ir_place','ir_activate','renewal',
         'draft_sign','draft_pick_trade',
         'fa_offer','fa_offer_update','fa_auction_sign','arb_renewal',
         'waiver_place','waiver_claim',
         'ifa_offer','ifa_offer_update','ifa_signing')
    NOT NULL;
