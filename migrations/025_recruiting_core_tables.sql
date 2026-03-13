-- 025: Core recruiting tables — rankings, investments, commitments, state, config
--
-- These tables support the weighted-lottery recruiting system.
-- recruiting_board (024) is the explicit watchlist; these tables
-- handle rankings, point allocation, commitment resolution, and config.

CREATE TABLE IF NOT EXISTS recruiting_rankings (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    player_id       INT NOT NULL,
    league_year_id  INT NOT NULL,
    composite_score FLOAT NOT NULL DEFAULT 0,
    star_rating     TINYINT NOT NULL DEFAULT 1,
    rank_overall    INT NOT NULL DEFAULT 0,
    rank_by_ptype   INT NOT NULL DEFAULT 0,
    UNIQUE KEY uq_rank_player_year (player_id, league_year_id),
    INDEX idx_rank_year_star (league_year_id, star_rating),
    INDEX idx_rank_year_overall (league_year_id, rank_overall)
);

CREATE TABLE IF NOT EXISTS recruiting_investments (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    org_id          INT NOT NULL,
    player_id       INT NOT NULL,
    league_year_id  INT NOT NULL,
    week            INT NOT NULL,
    points          INT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_invest (org_id, player_id, league_year_id, week),
    INDEX idx_invest_player_year (player_id, league_year_id),
    INDEX idx_invest_org_year (org_id, league_year_id)
);

CREATE TABLE IF NOT EXISTS recruiting_commitments (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    player_id       INT NOT NULL,
    org_id          INT NOT NULL,
    league_year_id  INT NOT NULL,
    week_committed  INT NOT NULL,
    points_total    INT NOT NULL DEFAULT 0,
    star_rating     TINYINT NOT NULL DEFAULT 1,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_commit_player_year (player_id, league_year_id),
    INDEX idx_commit_year_week (league_year_id, week_committed)
);

CREATE TABLE IF NOT EXISTS recruiting_state (
    league_year_id  INT PRIMARY KEY,
    current_week    INT NOT NULL DEFAULT 0,
    status          ENUM('pending', 'active', 'complete') NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS recruiting_config (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    config_key      VARCHAR(64) NOT NULL,
    config_value    VARCHAR(255) NOT NULL,
    description     VARCHAR(255) DEFAULT NULL,
    UNIQUE KEY uq_config_key (config_key)
);
