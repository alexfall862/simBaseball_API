-- Fix scouting budgets: ensure config rows exist and update live budgets to 2000.
--
-- The prior migrations used UPDATE which silently no-oped when the config rows
-- didn't exist yet.  This uses INSERT ... ON DUPLICATE KEY UPDATE so the rows
-- are guaranteed to exist afterward.

-- 1) Upsert budget config values
INSERT INTO scouting_config (config_key, config_value, description)
VALUES ('mlb_budget_per_year', '2000', 'Annual scouting point budget for MLB orgs (1-30)')
ON DUPLICATE KEY UPDATE config_value = '2000';

INSERT INTO scouting_config (config_key, config_value, description)
VALUES ('college_budget_per_year', '2000', 'Annual scouting point budget for college orgs')
ON DUPLICATE KEY UPDATE config_value = '2000';

-- 2) Align draft scouting costs with pro scouting costs (10 for attrs, 50 for potential)
INSERT INTO scouting_config (config_key, config_value, description)
VALUES ('draft_attrs_precise_cost', '10', 'Cost to reveal precise attributes of a draft prospect')
ON DUPLICATE KEY UPDATE config_value = '10';

INSERT INTO scouting_config (config_key, config_value, description)
VALUES ('draft_potential_precise_cost', '50', 'Cost to reveal precise potentials of a draft prospect')
ON DUPLICATE KEY UPDATE config_value = '50';

-- 3) Update any existing scouting_budgets rows that were created at old totals.
--    Only raise the ceiling; spent_points are preserved.
UPDATE scouting_budgets SET total_points = 2000 WHERE total_points < 2000;

-- 4) Create scouting_dept_purchases table for tracking expansion purchases
CREATE TABLE IF NOT EXISTS `scouting_dept_purchases` (
  `id` int NOT NULL AUTO_INCREMENT,
  `org_id` int NOT NULL,
  `league_year_id` int unsigned NOT NULL,
  `tier` tinyint NOT NULL COMMENT 'Which tier was purchased (1-11)',
  `bonus_points` int NOT NULL COMMENT 'Points gained from this purchase',
  `cash_cost` decimal(15,2) NOT NULL COMMENT 'Cash deducted for this purchase',
  `ledger_entry_id` bigint DEFAULT NULL COMMENT 'FK to org_ledger_entries for rollback',
  `transaction_log_id` int DEFAULT NULL COMMENT 'FK to transaction_log for rollback',
  `rolled_back` tinyint NOT NULL DEFAULT 0,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_scouting_dept_org_year` (`org_id`, `league_year_id`),
  CONSTRAINT `fk_scouting_dept_org` FOREIGN KEY (`org_id`) REFERENCES `organizations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 5) Add scouting_purchase to transaction_log enum
ALTER TABLE `transaction_log`
  MODIFY COLUMN `transaction_type` enum(
    'trade','release','signing','extension','buyout',
    'promote','demote','ir_place','ir_activate','renewal',
    'draft_sign','draft_pick_trade',
    'fa_offer','fa_offer_update','fa_auction_sign',
    'arb_renewal',
    'waiver_place','waiver_claim',
    'ifa_offer','ifa_offer_update','ifa_signing',
    'scouting_purchase'
  ) NOT NULL;
