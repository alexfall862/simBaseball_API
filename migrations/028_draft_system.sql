-- 028: Draft system — state, picks, eligibility, signing, slot values, pick trades
--
-- Supports the weighted-lottery draft system with timer-based pick selection,
-- signing phase, and pick trading.

-- Draft configuration & state (one row per league_year)
CREATE TABLE IF NOT EXISTS draft_state (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    league_year_id    INT NOT NULL,
    total_rounds      INT NOT NULL DEFAULT 20,
    picks_per_round   INT NOT NULL DEFAULT 30,
    is_snake          TINYINT NOT NULL DEFAULT 0,
    seconds_per_pick  INT NOT NULL DEFAULT 60,
    phase             ENUM('SETUP','IN_PROGRESS','PAUSED','SIGNING','COMPLETE')
                      NOT NULL DEFAULT 'SETUP',
    current_round     INT NOT NULL DEFAULT 1,
    current_pick      INT NOT NULL DEFAULT 1,
    pick_deadline_at  DATETIME NULL,
    paused_remaining_s INT NULL,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_draft_year (league_year_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Individual pick slots (pre-populated at draft init)
CREATE TABLE IF NOT EXISTS draft_picks (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    league_year_id  INT NOT NULL,
    round           INT NOT NULL,
    pick_in_round   INT NOT NULL,
    overall_pick    INT NOT NULL,
    original_org_id INT NOT NULL,
    current_org_id  INT NOT NULL,
    player_id       INT NULL,
    picked_at       DATETIME NULL,
    is_auto_pick    TINYINT NOT NULL DEFAULT 0,
    INDEX idx_dp_year_overall (league_year_id, overall_pick),
    INDEX idx_dp_year_round (league_year_id, round, pick_in_round),
    INDEX idx_dp_org (current_org_id, league_year_id),
    INDEX idx_dp_player (player_id),
    UNIQUE KEY uq_dp_slot (league_year_id, round, pick_in_round)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Draft-eligible player pool for a given year
CREATE TABLE IF NOT EXISTS draft_eligible_players (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    player_id       INT NOT NULL,
    league_year_id  INT NOT NULL,
    source          ENUM('college','hs','intam') NOT NULL,
    draft_rank      INT NULL,
    UNIQUE KEY uq_dep (player_id, league_year_id),
    INDEX idx_dep_year_rank (league_year_id, draft_rank)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Signing status for each drafted player
CREATE TABLE IF NOT EXISTS draft_signing (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    draft_pick_id   INT NOT NULL,
    slot_value      DECIMAL(12,2) NOT NULL,
    status          ENUM('pending','signed','passed','refused') NOT NULL DEFAULT 'pending',
    signed_at       DATETIME NULL,
    contract_id     INT NULL,
    UNIQUE KEY uq_ds_pick (draft_pick_id),
    CONSTRAINT fk_ds_pick FOREIGN KEY (draft_pick_id)
        REFERENCES draft_picks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Slot value lookup (round -> base value)
CREATE TABLE IF NOT EXISTS draft_slot_values (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    round           INT NOT NULL,
    pick_in_round   INT NULL,
    slot_value      DECIMAL(12,2) NOT NULL,
    UNIQUE KEY uq_dsv (round, pick_in_round)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Draft pick trade tracking
CREATE TABLE IF NOT EXISTS draft_pick_trades (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    league_year_id  INT NOT NULL,
    round           INT NOT NULL,
    pick_in_round   INT NULL,
    from_org_id     INT NOT NULL,
    to_org_id       INT NOT NULL,
    trade_proposal_id INT NULL,
    traded_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_dpt_year (league_year_id),
    INDEX idx_dpt_from (from_org_id),
    INDEX idx_dpt_to (to_org_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Add draft transaction types to transaction_log ENUM
ALTER TABLE transaction_log
  MODIFY COLUMN transaction_type
    ENUM('trade','release','signing','extension','buyout',
         'promote','demote','ir_place','ir_activate','renewal',
         'draft_sign','draft_pick_trade') NOT NULL;
