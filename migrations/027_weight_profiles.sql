-- 027: Weight profiles — calibrated and manual position weight sets
--
-- Stores multiple named weight profiles so admins can compare hand-tuned
-- defaults against statistically-derived (OLS regression) weights.
-- Activating a profile writes its entries into rating_overall_weights,
-- which already flows through _compute_derived_raw_ratings().

CREATE TABLE IF NOT EXISTS weight_profiles (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    source          ENUM('calibrated','manual','default') NOT NULL DEFAULT 'manual',
    is_active       TINYINT NOT NULL DEFAULT 0,
    league_year_id  INT UNSIGNED,
    league_level    INT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS weight_profile_entries (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    profile_id      INT NOT NULL,
    rating_type     VARCHAR(50) NOT NULL,
    attribute_key   VARCHAR(50) NOT NULL,
    weight          FLOAT NOT NULL DEFAULT 0,
    UNIQUE KEY uq_wpe (profile_id, rating_type, attribute_key),
    CONSTRAINT fk_wpe_profile FOREIGN KEY (profile_id)
        REFERENCES weight_profiles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS calibration_runs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    profile_id      INT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    config_json     TEXT,
    results_json    TEXT,
    CONSTRAINT fk_cr_profile FOREIGN KEY (profile_id)
        REFERENCES weight_profiles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed the hand-tuned default profile
INSERT INTO weight_profiles (name, description, source, is_active)
VALUES ('Default (Hand-Tuned)', 'Original hand-tuned position weights from _DEFAULT_POSITION_WEIGHTS', 'default', 1);

SET @pid = LAST_INSERT_ID();

-- c_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'c_rating', 'power_base', 0.025),
(@pid, 'c_rating', 'contact_base', 0.025),
(@pid, 'c_rating', 'eye_base', 0.025),
(@pid, 'c_rating', 'discipline_base', 0.025),
(@pid, 'c_rating', 'basereaction_base', 0.025),
(@pid, 'c_rating', 'baserunning_base', 0.025),
(@pid, 'c_rating', 'throwacc_base', 0.05),
(@pid, 'c_rating', 'throwpower_base', 0.05),
(@pid, 'c_rating', 'catchframe_base', 0.25),
(@pid, 'c_rating', 'catchsequence_base', 0.25),
(@pid, 'c_rating', 'fieldcatch_base', 0.05),
(@pid, 'c_rating', 'fieldreact_base', 0.15),
(@pid, 'c_rating', 'fieldspot_base', 0.05);

-- fb_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'fb_rating', 'power_base', 0.175),
(@pid, 'fb_rating', 'contact_base', 0.175),
(@pid, 'fb_rating', 'eye_base', 0.175),
(@pid, 'fb_rating', 'discipline_base', 0.175),
(@pid, 'fb_rating', 'basereaction_base', 0.025),
(@pid, 'fb_rating', 'baserunning_base', 0.025),
(@pid, 'fb_rating', 'speed_base', 0.025),
(@pid, 'fb_rating', 'throwacc_base', 0.025),
(@pid, 'fb_rating', 'fieldcatch_base', 0.05),
(@pid, 'fb_rating', 'fieldreact_base', 0.10),
(@pid, 'fb_rating', 'fieldspot_base', 0.05);

-- sb_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'sb_rating', 'power_base', 0.1),
(@pid, 'sb_rating', 'contact_base', 0.1),
(@pid, 'sb_rating', 'eye_base', 0.1),
(@pid, 'sb_rating', 'discipline_base', 0.1),
(@pid, 'sb_rating', 'basereaction_base', 0.025),
(@pid, 'sb_rating', 'baserunning_base', 0.025),
(@pid, 'sb_rating', 'speed_base', 0.050),
(@pid, 'sb_rating', 'throwacc_base', 0.15),
(@pid, 'sb_rating', 'throwpower_base', 0.05),
(@pid, 'sb_rating', 'fieldcatch_base', 0.10),
(@pid, 'sb_rating', 'fieldreact_base', 0.15),
(@pid, 'sb_rating', 'fieldspot_base', 0.05);

-- tb_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'tb_rating', 'power_base', 0.125),
(@pid, 'tb_rating', 'contact_base', 0.125),
(@pid, 'tb_rating', 'eye_base', 0.125),
(@pid, 'tb_rating', 'discipline_base', 0.125),
(@pid, 'tb_rating', 'basereaction_base', 0.025),
(@pid, 'tb_rating', 'baserunning_base', 0.025),
(@pid, 'tb_rating', 'throwacc_base', 0.10),
(@pid, 'tb_rating', 'throwpower_base', 0.10),
(@pid, 'tb_rating', 'fieldcatch_base', 0.05),
(@pid, 'tb_rating', 'fieldreact_base', 0.15),
(@pid, 'tb_rating', 'fieldspot_base', 0.05);

-- ss_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'ss_rating', 'power_base', 0.0375),
(@pid, 'ss_rating', 'contact_base', 0.0375),
(@pid, 'ss_rating', 'eye_base', 0.0375),
(@pid, 'ss_rating', 'discipline_base', 0.0375),
(@pid, 'ss_rating', 'basereaction_base', 0.025),
(@pid, 'ss_rating', 'baserunning_base', 0.025),
(@pid, 'ss_rating', 'speed_base', 0.10),
(@pid, 'ss_rating', 'throwacc_base', 0.15),
(@pid, 'ss_rating', 'throwpower_base', 0.15),
(@pid, 'ss_rating', 'fieldcatch_base', 0.15),
(@pid, 'ss_rating', 'fieldreact_base', 0.25),
(@pid, 'ss_rating', 'fieldspot_base', 0.10);

-- lf_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'lf_rating', 'power_base', 0.1),
(@pid, 'lf_rating', 'contact_base', 0.1),
(@pid, 'lf_rating', 'eye_base', 0.1),
(@pid, 'lf_rating', 'discipline_base', 0.1),
(@pid, 'lf_rating', 'basereaction_base', 0.025),
(@pid, 'lf_rating', 'baserunning_base', 0.025),
(@pid, 'lf_rating', 'speed_base', 0.10),
(@pid, 'lf_rating', 'throwacc_base', 0.10),
(@pid, 'lf_rating', 'throwpower_base', 0.05),
(@pid, 'lf_rating', 'fieldcatch_base', 0.10),
(@pid, 'lf_rating', 'fieldreact_base', 0.05),
(@pid, 'lf_rating', 'fieldspot_base', 0.15);

-- cf_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'cf_rating', 'power_base', 0.025),
(@pid, 'cf_rating', 'contact_base', 0.025),
(@pid, 'cf_rating', 'eye_base', 0.025),
(@pid, 'cf_rating', 'discipline_base', 0.025),
(@pid, 'cf_rating', 'basereaction_base', 0.025),
(@pid, 'cf_rating', 'baserunning_base', 0.025),
(@pid, 'cf_rating', 'speed_base', 0.15),
(@pid, 'cf_rating', 'throwacc_base', 0.10),
(@pid, 'cf_rating', 'throwpower_base', 0.15),
(@pid, 'cf_rating', 'fieldcatch_base', 0.15),
(@pid, 'cf_rating', 'fieldreact_base', 0.20),
(@pid, 'cf_rating', 'fieldspot_base', 0.15);

-- rf_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'rf_rating', 'power_base', 0.1),
(@pid, 'rf_rating', 'contact_base', 0.1),
(@pid, 'rf_rating', 'eye_base', 0.1),
(@pid, 'rf_rating', 'discipline_base', 0.1),
(@pid, 'rf_rating', 'basereaction_base', 0.025),
(@pid, 'rf_rating', 'baserunning_base', 0.025),
(@pid, 'rf_rating', 'speed_base', 0.10),
(@pid, 'rf_rating', 'throwacc_base', 0.05),
(@pid, 'rf_rating', 'throwpower_base', 0.10),
(@pid, 'rf_rating', 'fieldcatch_base', 0.10),
(@pid, 'rf_rating', 'fieldreact_base', 0.05),
(@pid, 'rf_rating', 'fieldspot_base', 0.15);

-- dh_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'dh_rating', 'power_base', 0.10),
(@pid, 'dh_rating', 'contact_base', 0.10),
(@pid, 'dh_rating', 'eye_base', 0.10),
(@pid, 'dh_rating', 'discipline_base', 0.10),
(@pid, 'dh_rating', 'basereaction_base', 0.025),
(@pid, 'dh_rating', 'baserunning_base', 0.025),
(@pid, 'dh_rating', 'speed_base', 0.025);

-- sp_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'sp_rating', 'fieldcatch_base', 0.025),
(@pid, 'sp_rating', 'fieldreact_base', 0.05),
(@pid, 'sp_rating', 'fieldspot_base', 0.025),
(@pid, 'sp_rating', 'pendurance_base', 0.20),
(@pid, 'sp_rating', 'pgencontrol_base', 0.10),
(@pid, 'sp_rating', 'psequencing_base', 0.20),
(@pid, 'sp_rating', 'pthrowpower_base', 0.05),
(@pid, 'sp_rating', 'pickoff_base', 0.05),
(@pid, 'sp_rating', 'pitch1_ovr', 0.10),
(@pid, 'sp_rating', 'pitch2_ovr', 0.10),
(@pid, 'sp_rating', 'pitch3_ovr', 0.10),
(@pid, 'sp_rating', 'pitch4_ovr', 0.05),
(@pid, 'sp_rating', 'pitch5_ovr', 0.05);

-- rp_rating
INSERT INTO weight_profile_entries (profile_id, rating_type, attribute_key, weight) VALUES
(@pid, 'rp_rating', 'fieldcatch_base', 0.025),
(@pid, 'rp_rating', 'fieldreact_base', 0.05),
(@pid, 'rp_rating', 'fieldspot_base', 0.025),
(@pid, 'rp_rating', 'pendurance_base', 0.05),
(@pid, 'rp_rating', 'pgencontrol_base', 0.10),
(@pid, 'rp_rating', 'psequencing_base', 0.025),
(@pid, 'rp_rating', 'pthrowpower_base', 0.05),
(@pid, 'rp_rating', 'pickoff_base', 0.025),
(@pid, 'rp_rating', 'pitch1_ovr', 0.25),
(@pid, 'rp_rating', 'pitch2_ovr', 0.20),
(@pid, 'rp_rating', 'pitch3_ovr', 0.15),
(@pid, 'rp_rating', 'pitch4_ovr', 0.10),
(@pid, 'rp_rating', 'pitch5_ovr', 0.05);
