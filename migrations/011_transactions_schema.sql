-- Migration 011: Transaction system schema
-- Adds transaction audit log, trade proposal workflow, and soft roster limits.

-- 1. Transaction log — records every completed roster/financial move
CREATE TABLE IF NOT EXISTS transaction_log (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    transaction_type ENUM('trade','release','signing','extension','buyout',
                          'promote','demote','ir_place','ir_activate') NOT NULL,
    league_year_id   INT NOT NULL,
    primary_org_id   INT NOT NULL,
    secondary_org_id INT NULL,
    contract_id      INT NULL,
    player_id        INT NULL,
    details          JSON NOT NULL,
    executed_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    executed_by      VARCHAR(100) NULL,
    notes            VARCHAR(500) NULL,
    INDEX idx_txlog_org    (primary_org_id, league_year_id),
    INDEX idx_txlog_type   (transaction_type),
    INDEX idx_txlog_player (player_id)
);

-- 2. Trade proposals — multi-step approval workflow
CREATE TABLE IF NOT EXISTS trade_proposals (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    proposing_org_id      INT NOT NULL,
    receiving_org_id      INT NOT NULL,
    league_year_id        INT NOT NULL,
    status                ENUM('proposed','counterparty_accepted',
                               'counterparty_rejected','admin_approved',
                               'admin_rejected','executed','cancelled',
                               'expired') NOT NULL DEFAULT 'proposed',
    proposal              JSON NOT NULL,
    proposed_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    counterparty_acted_at DATETIME NULL,
    admin_acted_at        DATETIME NULL,
    executed_at           DATETIME NULL,
    counterparty_note     VARCHAR(500) NULL,
    admin_note            VARCHAR(500) NULL,
    INDEX idx_tp_status    (status),
    INDEX idx_tp_orgs      (proposing_org_id, receiving_org_id),
    INDEX idx_tp_receiving (receiving_org_id, status)
);

-- 3. Soft roster limits on levels table
ALTER TABLE levels ADD COLUMN max_roster INT NULL DEFAULT NULL;

UPDATE levels SET max_roster = 26  WHERE id = 9;  -- MLB
UPDATE levels SET max_roster = 28  WHERE id = 8;  -- AAA
UPDATE levels SET max_roster = 28  WHERE id = 7;  -- AA
UPDATE levels SET max_roster = 28  WHERE id = 6;  -- High-A
UPDATE levels SET max_roster = 28  WHERE id = 5;  -- A
-- Scraps (id=4) stays NULL = unlimited
