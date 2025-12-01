-- Timestamp Table for Global Simulation State
-- This is a SINGLE-ROW table (ID=1) that tracks where the simulation currently is.
-- The frontend connects via WebSocket and receives this data whenever state changes.

CREATE TABLE IF NOT EXISTS timestamp_state (
    id INT PRIMARY KEY DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Current simulation position
    season INT NOT NULL DEFAULT 2026,              -- e.g., 2026
    season_id INT NOT NULL DEFAULT 1,              -- FK to seasons table (internal ID)
    week INT NOT NULL DEFAULT 1,                   -- Current week number (1-30+)
    week_id INT DEFAULT NULL,                      -- Internal week identifier (optional)

    -- Game day tracking (which subweeks have run this week)
    games_a_ran BOOLEAN NOT NULL DEFAULT FALSE,    -- Subweek A complete
    games_b_ran BOOLEAN NOT NULL DEFAULT FALSE,    -- Subweek B complete
    games_c_ran BOOLEAN NOT NULL DEFAULT FALSE,    -- Subweek C complete
    games_d_ran BOOLEAN NOT NULL DEFAULT FALSE,    -- Subweek D complete

    -- Phase flags
    is_offseason BOOLEAN NOT NULL DEFAULT FALSE,   -- True during offseason
    is_recruiting_locked BOOLEAN NOT NULL DEFAULT TRUE,   -- True when recruiting is frozen
    is_free_agency_locked BOOLEAN NOT NULL DEFAULT TRUE,  -- True when FA is frozen
    is_draft_time BOOLEAN NOT NULL DEFAULT FALSE,  -- True during draft period

    -- Sync status flags
    run_games BOOLEAN NOT NULL DEFAULT FALSE,      -- Is simulation actively running games?
    run_cron BOOLEAN NOT NULL DEFAULT FALSE,       -- Is background cron running?
    recruiting_synced BOOLEAN NOT NULL DEFAULT TRUE,      -- Has recruiting AI completed?
    gm_actions_completed BOOLEAN NOT NULL DEFAULT TRUE,   -- Have AI GMs completed actions?

    -- Free agency tracking
    free_agency_round INT NOT NULL DEFAULT 0,      -- Current FA round (0 if not in FA)

    -- Enforce single-row constraint
    CONSTRAINT single_row CHECK (id = 1)
);

-- Insert the initial row (ID=1)
INSERT INTO timestamp_state (id, season, season_id, week)
VALUES (1, 2026, 1, 1)
ON DUPLICATE KEY UPDATE id = id;

-- Create index for fast lookups (though there's only one row)
CREATE INDEX IF NOT EXISTS idx_timestamp_updated ON timestamp_state(updated_at);
