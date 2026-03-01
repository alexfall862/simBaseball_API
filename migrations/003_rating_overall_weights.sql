-- 003_rating_overall_weights.sql
-- Configurable weights for pitcher and position player overall ratings.
-- Admins can adjust weights via the admin panel; re-seed to recalculate.

CREATE TABLE IF NOT EXISTS rating_overall_weights (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    rating_type     VARCHAR(50)  NOT NULL,   -- 'pitcher_overall' or 'position_overall'
    attribute_key   VARCHAR(50)  NOT NULL,   -- e.g. 'power_base', 'pitch1_ovr'
    weight          FLOAT        NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_overall_weight (rating_type, attribute_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- Default position player overall weights (sum = 1.0)
-- Balanced across batting, speed/baserunning, defense
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('position_overall', 'power_base',        0.12),
    ('position_overall', 'contact_base',      0.12),
    ('position_overall', 'discipline_base',   0.08),
    ('position_overall', 'eye_base',          0.08),
    ('position_overall', 'speed_base',        0.08),
    ('position_overall', 'baserunning_base',  0.05),
    ('position_overall', 'basereaction_base', 0.05),
    ('position_overall', 'throwacc_base',     0.06),
    ('position_overall', 'throwpower_base',   0.06),
    ('position_overall', 'fieldcatch_base',   0.08),
    ('position_overall', 'fieldreact_base',   0.10),
    ('position_overall', 'fieldspot_base',    0.07),
    ('position_overall', 'catchframe_base',   0.025),
    ('position_overall', 'catchsequence_base',0.025)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Default pitcher overall weights (sum = 1.0)
-- Pitching attributes + pitch quality
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('pitcher_overall', 'pendurance_base',    0.12),
    ('pitcher_overall', 'pgencontrol_base',   0.10),
    ('pitcher_overall', 'psequencing_base',   0.12),
    ('pitcher_overall', 'pthrowpower_base',   0.06),
    ('pitcher_overall', 'pickoff_base',       0.04),
    ('pitcher_overall', 'fieldcatch_base',    0.02),
    ('pitcher_overall', 'fieldreact_base',    0.02),
    ('pitcher_overall', 'fieldspot_base',     0.02),
    ('pitcher_overall', 'pitch1_ovr',         0.15),
    ('pitcher_overall', 'pitch2_ovr',         0.12),
    ('pitcher_overall', 'pitch3_ovr',         0.10),
    ('pitcher_overall', 'pitch4_ovr',         0.07),
    ('pitcher_overall', 'pitch5_ovr',         0.06)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
