-- Season 2: free agency and international signing durability (docs/FREE_AGENCY_DIAGNOSTIC.md).
-- Apply after season2_progression_camp.sql. Idempotent: guarded ADD COLUMNs,
-- MODIFY COLUMN to the same enum, CREATE IF NOT EXISTS, INSERT IGNORE. Works
-- with the mysql client and with scripts/season2_camp_migration.py.

-- ── Offers: a winning offer whose signing fails is marked 'failed' and the
--    next-best offer is tried; score and failure reason are kept. ──
ALTER TABLE fa_auction_offers
  MODIFY COLUMN status ENUM('active','outbid','withdrawn','won','lost','failed') NOT NULL DEFAULT 'active';

-- International signing offers get the same 'failed' status (winner could not be signed).
ALTER TABLE ifa_auction_offers
  MODIFY COLUMN status ENUM('active','outbid','withdrawn','won','lost','failed') NOT NULL DEFAULT 'active';

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fa_auction_offers' AND COLUMN_NAME = 'score') = 0,
    'ALTER TABLE fa_auction_offers ADD COLUMN score DECIMAL(8,5) NULL AFTER status, ADD COLUMN fail_reason VARCHAR(255) NULL AFTER score',
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── Auctions: outcome data and falling asks ──
SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fa_auction' AND COLUMN_NAME = 'outcome') = 0,
    'ALTER TABLE fa_auction
       ADD COLUMN outcome ENUM(''signed'',''expired_no_offers'',''all_offers_failed'') NULL AFTER winning_offer_id,
       ADD COLUMN initial_min_aav DECIMAL(18,2) NULL AFTER outcome,
       ADD COLUMN initial_min_total_value DECIMAL(18,2) NULL AFTER initial_min_aav,
       ADD COLUMN rounds_without_offer INT NOT NULL DEFAULT 0 AFTER initial_min_total_value,
       ADD COLUMN ask_decay_steps INT NOT NULL DEFAULT 0 AFTER rounds_without_offer,
       ADD COLUMN bidder_count INT NULL AFTER ask_decay_steps,
       ADD COLUMN winning_score DECIMAL(8,5) NULL AFTER bidder_count,
       ADD COLUMN closed_week INT NULL AFTER winning_score,
       ADD COLUMN closed_at DATETIME NULL AFTER closed_week',
    'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Existing auctions: their current ask is their starting ask.
UPDATE fa_auction SET initial_min_aav = min_aav, initial_min_total_value = min_total_value
WHERE initial_min_aav IS NULL;

-- ── Per-club API tokens for club-scoped writes (FA offers) ──
CREATE TABLE IF NOT EXISTS org_api_tokens (
  org_id        INT          NOT NULL,
  token_hash    CHAR(64)     NOT NULL,
  token_hint    VARCHAR(8)   NOT NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  rotated_at    DATETIME     NULL,
  last_used_at  DATETIME     NULL,
  PRIMARY KEY (org_id),
  UNIQUE KEY uq_org_token_hash (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Settings ──
INSERT IGNORE INTO fa_config (config_key, config_value, description) VALUES
  ('fa_ask_decay_pct',            '0.10', 'Falling asks: share an unbid player lowers his ask by each round'),
  ('fa_ask_decay_after_rounds',   '2',    'Falling asks: rounds without an offer before the ask starts to fall'),
  ('fa_reserve_offer_commitments','1',    'Offers reserve their commitment against the club''s cash while active (1 on, 0 off)'),
  ('fa_commitment_includes_salary','1',   'The reserved commitment includes the first season''s salary, not only the bonus (1 on, 0 off)'),
  ('market_rate_method',          'median', 'Market rate: median of per-signing AAV/WAR (median) or ratio of sums (ratio)'),
  ('market_rate_max_change',      '0.15', 'Market rate may move at most this share from the previous season''s rate');
