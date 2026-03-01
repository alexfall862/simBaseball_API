-- 008_gameplanning_schema.sql
-- Adds missing strategy columns to playerStrategies,
-- creates team_strategy and team_bullpen_order tables.

-- -------------------------------------------------------
-- A. Add columns to playerStrategies
-- -------------------------------------------------------

ALTER TABLE playerStrategies
  ADD COLUMN stealfreq    DECIMAL(5,2) DEFAULT NULL,
  ADD COLUMN pickofffreq  DECIMAL(5,2) DEFAULT NULL,
  ADD COLUMN pitchchoices JSON         DEFAULT NULL,
  ADD COLUMN left_split   DECIMAL(5,4) DEFAULT NULL,
  ADD COLUMN center_split DECIMAL(5,4) DEFAULT NULL,
  ADD COLUMN right_split  DECIMAL(5,4) DEFAULT NULL,
  ADD COLUMN pitchpull    INT          DEFAULT NULL COMMENT 'pitch count to consider pulling; NULL = use team default',
  ADD COLUMN pulltend     ENUM('normal','quick','long') DEFAULT NULL COMMENT 'leash tendency; NULL = normal';


-- -------------------------------------------------------
-- B. Create team_strategy table
-- -------------------------------------------------------

CREATE TABLE IF NOT EXISTS team_strategy (
    id                    INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    team_id               INT NOT NULL,
    outfield_spacing      ENUM('normal','deep','shallow','shift_pull','shift_oppo') NOT NULL DEFAULT 'normal',
    infield_spacing       ENUM('normal','in','double_play','shift_pull','shift_oppo') NOT NULL DEFAULT 'normal',
    bullpen_cutoff        INT NOT NULL DEFAULT 100 COMMENT 'pitch count at which SP is considered for pull',
    bullpen_priority      ENUM('rest','matchup','best_available') NOT NULL DEFAULT 'rest',
    emergency_pitcher_id  INT DEFAULT NULL COMMENT 'player_id of emergency position-player pitcher',
    intentional_walk_list JSON DEFAULT NULL COMMENT 'array of opposing player_ids to IBB',
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_team_strategy (team_id),

    CONSTRAINT fk_ts_team
        FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE,
    CONSTRAINT fk_ts_emergency
        FOREIGN KEY (emergency_pitcher_id) REFERENCES simbbPlayers (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- -------------------------------------------------------
-- C. Create team_bullpen_order table
-- -------------------------------------------------------

CREATE TABLE IF NOT EXISTS team_bullpen_order (
    id        INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    team_id   INT NOT NULL,
    slot      INT NOT NULL COMMENT '1-based ordering slot',
    player_id INT NOT NULL,
    role      ENUM('closer','setup','middle','long','mop_up') NOT NULL DEFAULT 'middle',

    UNIQUE KEY uq_bp_team_slot (team_id, slot),

    CONSTRAINT fk_bp_team
        FOREIGN KEY (team_id) REFERENCES teams (id) ON DELETE CASCADE,
    CONSTRAINT fk_bp_player
        FOREIGN KEY (player_id) REFERENCES simbbPlayers (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
