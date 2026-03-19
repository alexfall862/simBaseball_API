-- 039_resim_idempotency.sql
-- Adds columns/tables needed for safe re-simulation of already-played games.
--
-- 1) stamina_cost on per-game lines so stamina drain can be reversed
-- 2) game_fielding_lines so fielding stats can be reversed (mirrors player_fielding_stats)

-- -----------------------------------------------------------------------
-- stamina_cost on per-game batting and pitching lines
-- -----------------------------------------------------------------------
ALTER TABLE game_batting_lines
    ADD COLUMN stamina_cost INT DEFAULT NULL AFTER inside_the_park_hr;

ALTER TABLE game_pitching_lines
    ADD COLUMN stamina_cost INT DEFAULT NULL AFTER inside_the_park_hr_allowed;

-- -----------------------------------------------------------------------
-- game_fielding_lines — per-game fielding stats for reversal on re-sim
-- (mirrors the columns used in player_fielding_stats season accumulation)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS game_fielding_lines (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    game_id       INT             NOT NULL,
    player_id     BIGINT UNSIGNED NOT NULL,
    team_id       INT             NOT NULL,
    league_year_id INT            NOT NULL,
    position_code VARCHAR(16)     NOT NULL,
    innings       INT             NOT NULL DEFAULT 0,
    putouts       INT             NOT NULL DEFAULT 0,
    assists       INT             NOT NULL DEFAULT 0,
    errors        INT             NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_game_fielding (game_id, player_id, position_code),
    INDEX idx_gfl_player (player_id, league_year_id),
    CONSTRAINT fk_gfl_game FOREIGN KEY (game_id) REFERENCES gamelist(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
