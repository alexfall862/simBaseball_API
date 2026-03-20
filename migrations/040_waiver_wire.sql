-- 040_waiver_wire.sql
-- Waiver wire system for mid-season player releases.
--
-- Run via Python migration: POST /admin/migrations/add-waiver-tables
-- Or apply this SQL directly.

-- -----------------------------------------------------------------------
-- waiver_claims — tracks players placed on waivers after release
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS waiver_claims (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    player_id        INT             NOT NULL,
    contract_id      INT             NOT NULL,
    releasing_org_id INT             NOT NULL,
    league_year_id   INT             NOT NULL,
    placed_week      INT             NOT NULL,
    expires_week     INT             NOT NULL,
    status           ENUM('active','claimed','cleared','cancelled')
                         NOT NULL DEFAULT 'active',
    claiming_org_id  INT             NULL,
    resolved_at      DATETIME        NULL,
    transaction_id   INT             NULL,
    claim_transaction_id INT          NULL,
    last_level       INT             NOT NULL,
    service_years    INT             NOT NULL DEFAULT 0,
    created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_wc_status (status),
    INDEX idx_wc_player (player_id),
    INDEX idx_wc_expires (expires_week, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------
-- waiver_claim_bids — individual org bids on waiver players
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS waiver_claim_bids (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    waiver_claim_id  INT             NOT NULL,
    org_id           INT             NOT NULL,
    created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_wcb_claim_org (waiver_claim_id, org_id),
    FOREIGN KEY (waiver_claim_id) REFERENCES waiver_claims(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- -----------------------------------------------------------------------
-- Extend transaction_log enum with waiver types
-- -----------------------------------------------------------------------
ALTER TABLE transaction_log
  MODIFY COLUMN transaction_type ENUM(
    'trade','release','signing','extension','buyout',
    'promote','demote','ir_place','ir_activate','renewal',
    'draft_sign','draft_pick_trade',
    'fa_offer','fa_offer_update','fa_auction_sign','arb_renewal',
    'waiver_place','waiver_claim'
  ) NOT NULL;
