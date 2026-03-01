-- 002_bootstrap_tables.sql
-- Adds notifications, news, and player stat accumulation tables
-- for the bootstrap landing endpoint.

-- -------------------------------------------------------
-- 1. notifications
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    team_id     INT NOT NULL,
    message     VARCHAR(500) NOT NULL,
    is_read     TINYINT(1) NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_notifications_team
        FOREIGN KEY (team_id) REFERENCES teams (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- -------------------------------------------------------
-- 2. news
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS news (
    id          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    team_id     INT NOT NULL,
    message     VARCHAR(500) NOT NULL,
    week        INT NOT NULL,
    season_id   INT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_news_team
        FOREIGN KEY (team_id) REFERENCES teams (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_news_season
        FOREIGN KEY (season_id) REFERENCES seasons (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- -------------------------------------------------------
-- 3. player_batting_stats
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_batting_stats (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    player_id       INT NOT NULL,
    league_year_id  INT UNSIGNED NOT NULL,
    team_id         INT NOT NULL,
    games           INT NOT NULL DEFAULT 0,
    at_bats         INT NOT NULL DEFAULT 0,
    runs            INT NOT NULL DEFAULT 0,
    hits            INT NOT NULL DEFAULT 0,
    doubles_hit     INT NOT NULL DEFAULT 0,
    triples         INT NOT NULL DEFAULT 0,
    home_runs       INT NOT NULL DEFAULT 0,
    rbi             INT NOT NULL DEFAULT 0,
    walks           INT NOT NULL DEFAULT 0,
    strikeouts      INT NOT NULL DEFAULT 0,
    stolen_bases    INT NOT NULL DEFAULT 0,
    caught_stealing INT NOT NULL DEFAULT 0,

    UNIQUE KEY uq_batting (player_id, league_year_id, team_id),

    CONSTRAINT fk_batting_player
        FOREIGN KEY (player_id) REFERENCES simbbPlayers (id) ON DELETE CASCADE,
    CONSTRAINT fk_batting_ly
        FOREIGN KEY (league_year_id) REFERENCES league_years (id) ON DELETE CASCADE,
    CONSTRAINT fk_batting_team
        FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- -------------------------------------------------------
-- 4. player_pitching_stats
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_pitching_stats (
    id                   INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    player_id            INT NOT NULL,
    league_year_id       INT UNSIGNED NOT NULL,
    team_id              INT NOT NULL,
    games                INT NOT NULL DEFAULT 0,
    games_started        INT NOT NULL DEFAULT 0,
    wins                 INT NOT NULL DEFAULT 0,
    losses               INT NOT NULL DEFAULT 0,
    saves                INT NOT NULL DEFAULT 0,
    innings_pitched_outs INT NOT NULL DEFAULT 0,
    hits_allowed         INT NOT NULL DEFAULT 0,
    runs_allowed         INT NOT NULL DEFAULT 0,
    earned_runs          INT NOT NULL DEFAULT 0,
    walks                INT NOT NULL DEFAULT 0,
    strikeouts           INT NOT NULL DEFAULT 0,
    home_runs_allowed    INT NOT NULL DEFAULT 0,

    UNIQUE KEY uq_pitching (player_id, league_year_id, team_id),

    CONSTRAINT fk_pitching_player
        FOREIGN KEY (player_id) REFERENCES simbbPlayers (id) ON DELETE CASCADE,
    CONSTRAINT fk_pitching_ly
        FOREIGN KEY (league_year_id) REFERENCES league_years (id) ON DELETE CASCADE,
    CONSTRAINT fk_pitching_team
        FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- -------------------------------------------------------
-- 5. player_fielding_stats
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_fielding_stats (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    player_id       INT NOT NULL,
    league_year_id  INT UNSIGNED NOT NULL,
    team_id         INT NOT NULL,
    position_code   VARCHAR(3) NOT NULL,
    games           INT NOT NULL DEFAULT 0,
    innings         INT NOT NULL DEFAULT 0,
    putouts         INT NOT NULL DEFAULT 0,
    assists         INT NOT NULL DEFAULT 0,
    errors          INT NOT NULL DEFAULT 0,

    UNIQUE KEY uq_fielding (player_id, league_year_id, team_id, position_code),

    CONSTRAINT fk_fielding_player
        FOREIGN KEY (player_id) REFERENCES simbbPlayers (id) ON DELETE CASCADE,
    CONSTRAINT fk_fielding_ly
        FOREIGN KEY (league_year_id) REFERENCES league_years (id) ON DELETE CASCADE,
    CONSTRAINT fk_fielding_team
        FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
