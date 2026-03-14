-- 026: Listed position — derived or user-overridden position per player per team
--
-- Every rostered player gets a single listed position (e.g. "ss", "sp", "rp").
-- Positions are auto-derived from ratings on season init and advance-week,
-- refined from gameplan data when users save depth charts / rotations,
-- and can be explicitly overridden by users.
--
-- source priority: override > gameplan > auto
-- The override-preserving upsert ensures auto/gameplan refreshes never
-- clobber a user's manual override.

CREATE TABLE IF NOT EXISTS player_listed_position (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    player_id       INT NOT NULL,
    team_id         INT NOT NULL,
    league_year_id  INT NOT NULL,
    position_code   VARCHAR(4) NOT NULL COMMENT 'c,fb,sb,tb,ss,lf,cf,rf,dh,sp,rp',
    source          ENUM('override','gameplan','auto') NOT NULL DEFAULT 'auto',
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_plp_player_team_year (player_id, team_id, league_year_id),
    INDEX idx_plp_team_year (team_id, league_year_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
