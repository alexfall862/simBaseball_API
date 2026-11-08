-- Season 2: progression QC, rating snapshots and training camp.
-- Apply once after season2_amateur_pipeline.sql. Everything here is idempotent
-- (CREATE IF NOT EXISTS / INSERT IGNORE / INSERT ... WHERE NOT EXISTS).

-- ── Growth curves: extend to age 50 with the age-45 values (age-related
--    regression is potential-agnostic by design; the tail just continues) ──
INSERT INTO growth_curves (grade, age, prog_min, prog_mode, prog_max)
SELECT g.grade, a.age, g.prog_min, g.prog_mode, g.prog_max
FROM growth_curves g
JOIN (SELECT 46 AS age UNION ALL SELECT 47 UNION ALL SELECT 48
      UNION ALL SELECT 49 UNION ALL SELECT 50) a
WHERE g.age = 45
  AND NOT EXISTS (SELECT 1 FROM growth_curves x WHERE x.grade = g.grade AND x.age = a.age);

-- ── Config: no automatic retirement on age alone; training-camp knobs ──
UPDATE league_config SET config_value = '0',
  description = 'Players at or above this age retire regardless of contract; 0 disables the rule'
WHERE config_key = 'retire_age_hard' AND config_value = '40';

INSERT IGNORE INTO league_config (config_key, config_value, description) VALUES
  ('camp_regular_steps',   '1',    'Training camp regular intensity: potential grade steps added for the year (no risk)'),
  ('camp_intense_steps',   '2',    'Training camp intense intensity: steps up on success / down on backfire'),
  ('camp_intense_backfire','0.25', 'Training camp intense intensity: backfire probability'),
  ('camp_max_steps',       '4',    'Training camp max intensity: steps up on success / down on backfire'),
  ('camp_max_backfire',    '0.50', 'Training camp max intensity: backfire probability');

-- ── Rating snapshots: true values before and after each progression ──
CREATE TABLE IF NOT EXISTS player_rating_snapshots (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  player_id      INT          NOT NULL,
  league_year_id INT          NOT NULL,
  stage          ENUM('pre_progression','post_progression') NOT NULL,
  age            INT          NOT NULL,
  level          TINYINT      NULL,
  org_id         INT          NULL,
  ptype          VARCHAR(10)  NULL,
  raw_ovr        DECIMAL(8,3) NULL,
  displayovr     TINYINT      NULL,
  attrs          JSON         NOT NULL,
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_prs (player_id, league_year_id, stage),
  KEY idx_prs_year_stage (league_year_id, stage),
  KEY idx_prs_player (player_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Realised progression per (grade, age) for the table-vs-actual report ──
CREATE TABLE IF NOT EXISTS progression_curve_stats (
  id             INT          NOT NULL AUTO_INCREMENT,
  league_year_id INT          NOT NULL,
  grade          VARCHAR(2)   NOT NULL,
  age            INT          NOT NULL,
  n              INT          NOT NULL,
  mean_delta     DECIMAL(7,3) NOT NULL,
  p10            DECIMAL(7,3) NOT NULL,
  p50            DECIMAL(7,3) NOT NULL,
  p90            DECIMAL(7,3) NOT NULL,
  table_min      FLOAT        NULL,
  table_mode     FLOAT        NULL,
  table_max      FLOAT        NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_pcs (league_year_id, grade, age)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Training camp: one focus skill per player per season, set by the org ──
CREATE TABLE IF NOT EXISTS training_camp_focus (
  id             INT          NOT NULL AUTO_INCREMENT,
  player_id      INT          NOT NULL,
  org_id         INT          NOT NULL,
  league_year_id INT          NOT NULL,
  attr           VARCHAR(32)  NOT NULL,
  intensity      ENUM('regular','intense','max') NOT NULL DEFAULT 'regular',
  set_by         VARCHAR(64)  NULL,
  updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_tcf (player_id, league_year_id),
  KEY idx_tcf_org_year (org_id, league_year_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS training_camp_results (
  id              INT          NOT NULL AUTO_INCREMENT,
  player_id       INT          NOT NULL,
  org_id          INT          NOT NULL,
  league_year_id  INT          NOT NULL,
  attr            VARCHAR(32)  NOT NULL,
  intensity       ENUM('regular','intense','max') NOT NULL,
  base_grade      VARCHAR(3)   NULL,
  effective_grade VARCHAR(3)   NULL,
  steps           TINYINT      NOT NULL,
  backfired       TINYINT(1)   NOT NULL DEFAULT 0,
  roll            DECIMAL(6,4) NOT NULL,
  pot_columns     JSON         NOT NULL,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_tcr (player_id, league_year_id),
  KEY idx_tcr_org_year (org_id, league_year_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
