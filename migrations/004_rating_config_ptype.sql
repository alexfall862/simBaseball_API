-- 004_rating_config_ptype.sql
-- Recreate rating_scale_config with:
--   1. ptype column  — separate distributions for Pitcher vs Position
--   2. quartile columns (p25, median, p75) — reference data from seed analysis
--
-- The admin ASSIGNS mean_value / std_dev (the values used for 20-80 conversion).
-- The seed populates initial values + quartiles as a ballpark reference.
-- Data is ephemeral (regenerated on every seed), so drop+recreate is safe.

DROP TABLE IF EXISTS rating_scale_config;

CREATE TABLE rating_scale_config (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    level_id        INT NOT NULL,
    ptype           VARCHAR(20) NOT NULL DEFAULT 'all',
    attribute_key   VARCHAR(50) NOT NULL,
    mean_value      DOUBLE NOT NULL DEFAULT 0,
    std_dev         DOUBLE NOT NULL DEFAULT 0,
    p25             DOUBLE DEFAULT NULL,
    median          DOUBLE DEFAULT NULL,
    p75             DOUBLE DEFAULT NULL,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_level_ptype_attr (level_id, ptype, attribute_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
