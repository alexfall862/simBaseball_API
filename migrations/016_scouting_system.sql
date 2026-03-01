-- Migration 016: Scouting system
-- Adds scouting_config, scouting_budgets, and scouting_actions tables.
-- Supports tiered information visibility with point-based unlock system.

-- 1. Configurable point costs and budget amounts (admin-tunable key-value)
CREATE TABLE IF NOT EXISTS scouting_config (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    config_key   VARCHAR(64) NOT NULL,
    config_value VARCHAR(255) NOT NULL,
    description  VARCHAR(255) NULL,
    UNIQUE KEY uq_config_key (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO scouting_config (config_key, config_value, description) VALUES
    ('mlb_budget_per_year',    '1000', 'Scouting points per MLB org per league year'),
    ('college_budget_per_year', '500', 'Scouting points per college org per league year'),
    ('hs_report_cost',          '10', 'Cost: HS text scouting report'),
    ('hs_potential_cost',       '25', 'Cost: HS potential grades unlock'),
    ('pro_numeric_cost',        '15', 'Cost: college/INTAM numeric attribute unlock');

-- 2. Per-org, per-year scouting budget (resets each league year)
CREATE TABLE IF NOT EXISTS scouting_budgets (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    org_id         INT NOT NULL,
    league_year_id INT UNSIGNED NOT NULL,
    total_points   INT NOT NULL DEFAULT 0,
    spent_points   INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_budget_org_year (org_id, league_year_id),

    CONSTRAINT fk_sb_org FOREIGN KEY (org_id) REFERENCES organizations (id) ON DELETE CASCADE,
    CONSTRAINT fk_sb_ly  FOREIGN KEY (league_year_id) REFERENCES league_years (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Records of what each org has unlocked on each player
--    UNIQUE on (org, player, action_type) without league_year —
--    once scouted, info persists across years.
CREATE TABLE IF NOT EXISTS scouting_actions (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    org_id         INT NOT NULL,
    league_year_id INT UNSIGNED NOT NULL,
    player_id      INT NOT NULL,
    action_type    ENUM('hs_report', 'hs_potential', 'pro_numeric') NOT NULL,
    points_spent   INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_action_org_player_type (org_id, player_id, action_type),
    INDEX idx_sa_org_year (org_id, league_year_id),
    INDEX idx_sa_player (player_id),

    CONSTRAINT fk_sa_org    FOREIGN KEY (org_id) REFERENCES organizations (id) ON DELETE CASCADE,
    CONSTRAINT fk_sa_ly     FOREIGN KEY (league_year_id) REFERENCES league_years (id) ON DELETE CASCADE,
    CONSTRAINT fk_sa_player FOREIGN KEY (player_id) REFERENCES simbbPlayers (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
