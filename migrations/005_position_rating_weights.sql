-- 005_position_rating_weights.sql
-- Seed per-position rating weights into rating_overall_weights.
-- These replace the hardcoded weight dicts in rating_config.py and rosters/__init__.py.
-- Weights are taken from the existing hardcoded values. Only non-zero weights stored.
-- Idempotent via ON DUPLICATE KEY UPDATE.

-- Catcher (batting 10%, base 5%, throwing 10%, catcher 50%, fielding 25%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('c_rating', 'power_base',         0.025),
    ('c_rating', 'contact_base',       0.025),
    ('c_rating', 'eye_base',           0.025),
    ('c_rating', 'discipline_base',    0.025),
    ('c_rating', 'basereaction_base',  0.025),
    ('c_rating', 'baserunning_base',   0.025),
    ('c_rating', 'throwacc_base',      0.05),
    ('c_rating', 'throwpower_base',    0.05),
    ('c_rating', 'catchframe_base',    0.25),
    ('c_rating', 'catchsequence_base', 0.25),
    ('c_rating', 'fieldcatch_base',    0.05),
    ('c_rating', 'fieldreact_base',    0.15),
    ('c_rating', 'fieldspot_base',     0.05)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- First Base (batting 70%, base 7.5%, throwing 2.5%, fielding 20%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('fb_rating', 'power_base',         0.175),
    ('fb_rating', 'contact_base',       0.175),
    ('fb_rating', 'eye_base',           0.175),
    ('fb_rating', 'discipline_base',    0.175),
    ('fb_rating', 'basereaction_base',  0.025),
    ('fb_rating', 'baserunning_base',   0.025),
    ('fb_rating', 'speed_base',         0.025),
    ('fb_rating', 'throwacc_base',      0.025),
    ('fb_rating', 'fieldcatch_base',    0.05),
    ('fb_rating', 'fieldreact_base',    0.10),
    ('fb_rating', 'fieldspot_base',     0.05)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Second Base (batting 40%, base 10%, throwing 20%, fielding 30%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('sb_rating', 'power_base',         0.1),
    ('sb_rating', 'contact_base',       0.1),
    ('sb_rating', 'eye_base',           0.1),
    ('sb_rating', 'discipline_base',    0.1),
    ('sb_rating', 'basereaction_base',  0.025),
    ('sb_rating', 'baserunning_base',   0.025),
    ('sb_rating', 'speed_base',         0.050),
    ('sb_rating', 'throwacc_base',      0.15),
    ('sb_rating', 'throwpower_base',    0.05),
    ('sb_rating', 'fieldcatch_base',    0.10),
    ('sb_rating', 'fieldreact_base',    0.15),
    ('sb_rating', 'fieldspot_base',     0.05)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Third Base (batting 50%, base 5%, throwing 20%, fielding 25%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('tb_rating', 'power_base',         0.125),
    ('tb_rating', 'contact_base',       0.125),
    ('tb_rating', 'eye_base',           0.125),
    ('tb_rating', 'discipline_base',    0.125),
    ('tb_rating', 'basereaction_base',  0.025),
    ('tb_rating', 'baserunning_base',   0.025),
    ('tb_rating', 'throwacc_base',      0.10),
    ('tb_rating', 'throwpower_base',    0.10),
    ('tb_rating', 'fieldcatch_base',    0.05),
    ('tb_rating', 'fieldreact_base',    0.15),
    ('tb_rating', 'fieldspot_base',     0.05)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Shortstop (batting 15%, base 15%, throwing 30%, fielding 40%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('ss_rating', 'power_base',         0.0375),
    ('ss_rating', 'contact_base',       0.0375),
    ('ss_rating', 'eye_base',           0.0375),
    ('ss_rating', 'discipline_base',    0.0375),
    ('ss_rating', 'basereaction_base',  0.025),
    ('ss_rating', 'baserunning_base',   0.025),
    ('ss_rating', 'speed_base',         0.10),
    ('ss_rating', 'throwacc_base',      0.15),
    ('ss_rating', 'throwpower_base',    0.15),
    ('ss_rating', 'fieldcatch_base',    0.15),
    ('ss_rating', 'fieldreact_base',    0.25),
    ('ss_rating', 'fieldspot_base',     0.10)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Left Field (batting 40%, base 15%, throwing 15%, fielding 30%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('lf_rating', 'power_base',         0.1),
    ('lf_rating', 'contact_base',       0.1),
    ('lf_rating', 'eye_base',           0.1),
    ('lf_rating', 'discipline_base',    0.1),
    ('lf_rating', 'basereaction_base',  0.025),
    ('lf_rating', 'baserunning_base',   0.025),
    ('lf_rating', 'speed_base',         0.10),
    ('lf_rating', 'throwacc_base',      0.10),
    ('lf_rating', 'throwpower_base',    0.05),
    ('lf_rating', 'fieldcatch_base',    0.10),
    ('lf_rating', 'fieldreact_base',    0.05),
    ('lf_rating', 'fieldspot_base',     0.15)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Center Field (batting 10%, base 15%, throwing 25%, fielding 50%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('cf_rating', 'power_base',         0.025),
    ('cf_rating', 'contact_base',       0.025),
    ('cf_rating', 'eye_base',           0.025),
    ('cf_rating', 'discipline_base',    0.025),
    ('cf_rating', 'basereaction_base',  0.025),
    ('cf_rating', 'baserunning_base',   0.025),
    ('cf_rating', 'speed_base',         0.15),
    ('cf_rating', 'throwacc_base',      0.10),
    ('cf_rating', 'throwpower_base',    0.15),
    ('cf_rating', 'fieldcatch_base',    0.15),
    ('cf_rating', 'fieldreact_base',    0.20),
    ('cf_rating', 'fieldspot_base',     0.15)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Right Field (batting 40%, base 15%, throwing 15%, fielding 30%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('rf_rating', 'power_base',         0.1),
    ('rf_rating', 'contact_base',       0.1),
    ('rf_rating', 'eye_base',           0.1),
    ('rf_rating', 'discipline_base',    0.1),
    ('rf_rating', 'basereaction_base',  0.025),
    ('rf_rating', 'baserunning_base',   0.025),
    ('rf_rating', 'speed_base',         0.10),
    ('rf_rating', 'throwacc_base',      0.05),
    ('rf_rating', 'throwpower_base',    0.10),
    ('rf_rating', 'fieldcatch_base',    0.10),
    ('rf_rating', 'fieldreact_base',    0.05),
    ('rf_rating', 'fieldspot_base',     0.15)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Designated Hitter (batting + base only)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('dh_rating', 'power_base',         0.10),
    ('dh_rating', 'contact_base',       0.10),
    ('dh_rating', 'eye_base',           0.10),
    ('dh_rating', 'discipline_base',    0.10),
    ('dh_rating', 'basereaction_base',  0.025),
    ('dh_rating', 'baserunning_base',   0.025),
    ('dh_rating', 'speed_base',         0.025)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Starting Pitcher (fielding 10%, pitching 60%, pitch quality 30%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('sp_rating', 'fieldcatch_base',    0.025),
    ('sp_rating', 'fieldreact_base',    0.05),
    ('sp_rating', 'fieldspot_base',     0.025),
    ('sp_rating', 'pendurance_base',    0.20),
    ('sp_rating', 'pgencontrol_base',   0.10),
    ('sp_rating', 'psequencing_base',   0.20),
    ('sp_rating', 'pthrowpower_base',   0.05),
    ('sp_rating', 'pickoff_base',       0.05),
    ('sp_rating', 'pitch1_ovr',         0.10),
    ('sp_rating', 'pitch2_ovr',         0.10),
    ('sp_rating', 'pitch3_ovr',         0.10),
    ('sp_rating', 'pitch4_ovr',         0.05),
    ('sp_rating', 'pitch5_ovr',         0.05)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);

-- Relief Pitcher (fielding 10%, pitching 25%, pitch quality 75%)
INSERT INTO rating_overall_weights (rating_type, attribute_key, weight) VALUES
    ('rp_rating', 'fieldcatch_base',    0.025),
    ('rp_rating', 'fieldreact_base',    0.05),
    ('rp_rating', 'fieldspot_base',     0.025),
    ('rp_rating', 'pendurance_base',    0.05),
    ('rp_rating', 'pgencontrol_base',   0.10),
    ('rp_rating', 'psequencing_base',   0.025),
    ('rp_rating', 'pthrowpower_base',   0.05),
    ('rp_rating', 'pickoff_base',       0.025),
    ('rp_rating', 'pitch1_ovr',         0.25),
    ('rp_rating', 'pitch2_ovr',         0.20),
    ('rp_rating', 'pitch3_ovr',         0.15),
    ('rp_rating', 'pitch4_ovr',         0.10),
    ('rp_rating', 'pitch5_ovr',         0.05)
ON DUPLICATE KEY UPDATE weight = VALUES(weight);
