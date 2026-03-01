-- 004_rating_config_ptype.sql
-- Add ptype column to rating_scale_config so distributions are computed
-- separately for pitchers vs position players.
--
-- Without this, mixing both player types produces bimodal distributions
-- with inflated stddev and means that don't vary across levels.

-- Easiest approach: drop and recreate with the new schema.
-- Data is ephemeral (regenerated on every seed), so no data loss.

DROP TABLE IF EXISTS rating_scale_config;

CREATE TABLE rating_scale_config (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    level_id        INT NOT NULL,
    ptype           VARCHAR(20) NOT NULL DEFAULT 'all',
    attribute_key   VARCHAR(50) NOT NULL,
    mean_value      DOUBLE NOT NULL DEFAULT 0,
    std_dev         DOUBLE NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_level_ptype_attr (level_id, ptype, attribute_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
