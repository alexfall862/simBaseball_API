-- 022_batting_lab.sql
-- Tables for the batting lab micro-simulation harness.

-- Run metadata (one row per triggered analysis)
CREATE TABLE IF NOT EXISTS batting_lab_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    label VARCHAR(128) NOT NULL DEFAULT '',
    league_level INT NOT NULL,
    games_per_scenario INT NOT NULL DEFAULT 50,
    scenario_type VARCHAR(32) NOT NULL DEFAULT 'tier_sweep',
    status ENUM('pending','running','complete','error') NOT NULL DEFAULT 'pending',
    error_message TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    INDEX idx_blr_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Aggregated per-scenario results
CREATE TABLE IF NOT EXISTS batting_lab_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    run_id INT NOT NULL,
    scenario_key VARCHAR(64) NOT NULL,
    tier_label VARCHAR(32) NOT NULL DEFAULT '',
    games_played INT NOT NULL DEFAULT 0,
    plate_appearances INT NOT NULL DEFAULT 0,
    at_bats INT NOT NULL DEFAULT 0,
    hits INT NOT NULL DEFAULT 0,
    doubles_ct INT NOT NULL DEFAULT 0,
    triples_ct INT NOT NULL DEFAULT 0,
    home_runs INT NOT NULL DEFAULT 0,
    walks INT NOT NULL DEFAULT 0,
    strikeouts INT NOT NULL DEFAULT 0,
    runs INT NOT NULL DEFAULT 0,
    rbi INT NOT NULL DEFAULT 0,
    stolen_bases INT NOT NULL DEFAULT 0,
    avg_score_home FLOAT NOT NULL DEFAULT 0,
    avg_score_away FLOAT NOT NULL DEFAULT 0,
    raw_json JSON NULL,
    UNIQUE KEY uq_blr_run_scenario (run_id, scenario_key),
    CONSTRAINT fk_blr_run FOREIGN KEY (run_id) REFERENCES batting_lab_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
