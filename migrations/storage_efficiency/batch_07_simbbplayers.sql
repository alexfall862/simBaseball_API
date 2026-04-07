-- =============================================================================
-- Batch 07: simbbPlayers VARCHAR(255) Right-Sizing
-- Table: simbbPlayers (player master — moderate row count)
-- Risk: Medium — verify all distinct values fit new sizes
-- Downtime: Table rebuild (moderate)
-- Primary benefit: Query performance (temp table / sort buffer allocation)
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PRE-FLIGHT: Verify distinct values and max lengths
-- ─────────────────────────────────────────────────────────────────────────────

-- Enum-like columns: verify all distinct values
SELECT 'bat_hand' AS col, bat_hand AS val, COUNT(*) AS cnt FROM simbbPlayers GROUP BY bat_hand
UNION ALL
SELECT 'pitch_hand', pitch_hand, COUNT(*) FROM simbbPlayers GROUP BY pitch_hand
UNION ALL
SELECT 'durability', durability, COUNT(*) FROM simbbPlayers GROUP BY durability
UNION ALL
SELECT 'injury_risk', injury_risk, COUNT(*) FROM simbbPlayers GROUP BY injury_risk
UNION ALL
SELECT 'ptype', ptype, COUNT(*) FROM simbbPlayers GROUP BY ptype
UNION ALL
SELECT 'intorusa', intorusa, COUNT(*) FROM simbbPlayers GROUP BY intorusa;

-- Max string lengths for sized VARCHAR columns
SELECT
  MAX(CHAR_LENGTH(arm_angle)) AS max_arm_angle,
  MAX(CHAR_LENGTH(firstname)) AS max_firstname,
  MAX(CHAR_LENGTH(lastname)) AS max_lastname,
  MAX(CHAR_LENGTH(area)) AS max_area,
  MAX(CHAR_LENGTH(city)) AS max_city,
  MAX(CHAR_LENGTH(pitch1_name)) AS max_pitch1,
  MAX(CHAR_LENGTH(pitch2_name)) AS max_pitch2,
  MAX(CHAR_LENGTH(pitch3_name)) AS max_pitch3,
  MAX(CHAR_LENGTH(pitch4_name)) AS max_pitch4,
  MAX(CHAR_LENGTH(pitch5_name)) AS max_pitch5
FROM simbbPlayers;

-- _pot columns: verify all values fit in VARCHAR(3)
SELECT
  MAX(CHAR_LENGTH(contact_pot)) AS max_contact_pot,
  MAX(CHAR_LENGTH(power_pot)) AS max_power_pot,
  MAX(CHAR_LENGTH(eye_pot)) AS max_eye_pot,
  MAX(CHAR_LENGTH(speed_pot)) AS max_speed_pot,
  MAX(CHAR_LENGTH(discipline_pot)) AS max_discipline_pot,
  MAX(CHAR_LENGTH(baserunning_pot)) AS max_baserun_pot,
  MAX(CHAR_LENGTH(basereaction_pot)) AS max_basereact_pot,
  MAX(CHAR_LENGTH(fieldcatch_pot)) AS max_fieldcatch_pot,
  MAX(CHAR_LENGTH(fieldreact_pot)) AS max_fieldreact_pot,
  MAX(CHAR_LENGTH(fieldspot_pot)) AS max_fieldspot_pot,
  MAX(CHAR_LENGTH(throwpower_pot)) AS max_throwpow_pot,
  MAX(CHAR_LENGTH(throwacc_pot)) AS max_throwacc_pot,
  MAX(CHAR_LENGTH(catchframe_pot)) AS max_catchfr_pot,
  MAX(CHAR_LENGTH(catchsequence_pot)) AS max_catchseq_pot,
  MAX(CHAR_LENGTH(pendurance_pot)) AS max_pendur_pot,
  MAX(CHAR_LENGTH(pgencontrol_pot)) AS max_pgenctrl_pot,
  MAX(CHAR_LENGTH(pickoff_pot)) AS max_pickoff_pot,
  MAX(CHAR_LENGTH(psequencing_pot)) AS max_pseq_pot,
  MAX(CHAR_LENGTH(pthrowpower_pot)) AS max_pthrowpow_pot
FROM simbbPlayers;
-- All values should be <= 3 (e.g., 'A+', 'B-', 'F', 'N')

-- Pitch-specific _pot columns
SELECT
  MAX(CHAR_LENGTH(pitch1_consist_pot)) AS p1_consist,
  MAX(CHAR_LENGTH(pitch1_pacc_pot)) AS p1_pacc,
  MAX(CHAR_LENGTH(pitch1_pbrk_pot)) AS p1_pbrk,
  MAX(CHAR_LENGTH(pitch1_pcntrl_pot)) AS p1_pcntrl,
  MAX(CHAR_LENGTH(pitch2_consist_pot)) AS p2_consist,
  MAX(CHAR_LENGTH(pitch2_pacc_pot)) AS p2_pacc,
  MAX(CHAR_LENGTH(pitch2_pbrk_pot)) AS p2_pbrk,
  MAX(CHAR_LENGTH(pitch2_pcntrl_pot)) AS p2_pcntrl,
  MAX(CHAR_LENGTH(pitch3_consist_pot)) AS p3_consist,
  MAX(CHAR_LENGTH(pitch3_pacc_pot)) AS p3_pacc,
  MAX(CHAR_LENGTH(pitch3_pbrk_pot)) AS p3_pbrk,
  MAX(CHAR_LENGTH(pitch3_pcntrl_pot)) AS p3_pcntrl,
  MAX(CHAR_LENGTH(pitch4_consist_pot)) AS p4_consist,
  MAX(CHAR_LENGTH(pitch4_pacc_pot)) AS p4_pacc,
  MAX(CHAR_LENGTH(pitch4_pbrk_pot)) AS p4_pbrk,
  MAX(CHAR_LENGTH(pitch4_pcntrl_pot)) AS p4_pcntrl,
  MAX(CHAR_LENGTH(pitch5_consist_pot)) AS p5_consist,
  MAX(CHAR_LENGTH(pitch5_pacc_pot)) AS p5_pacc,
  MAX(CHAR_LENGTH(pitch5_pbrk_pot)) AS p5_pbrk,
  MAX(CHAR_LENGTH(pitch5_pcntrl_pot)) AS p5_pcntrl
FROM simbbPlayers;

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'simbbPlayers';

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION: Right-size all VARCHAR(255) columns
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE simbbPlayers
  -- Demographic / identity columns
  MODIFY `firstname` varchar(50) DEFAULT NULL,
  MODIFY `lastname` varchar(50) DEFAULT NULL,
  MODIFY `area` varchar(60) DEFAULT NULL,
  MODIFY `city` varchar(60) DEFAULT NULL,

  -- Enum-like columns
  MODIFY `bat_hand` varchar(3) DEFAULT NULL,
  MODIFY `pitch_hand` varchar(3) DEFAULT NULL,
  MODIFY `arm_angle` varchar(20) DEFAULT NULL,
  MODIFY `durability` varchar(20) DEFAULT NULL,
  MODIFY `injury_risk` varchar(20) DEFAULT NULL,
  MODIFY `ptype` varchar(15) DEFAULT NULL,
  MODIFY `intorusa` varchar(15) DEFAULT NULL,

  -- Pitch names
  MODIFY `pitch1_name` varchar(30) DEFAULT NULL,
  MODIFY `pitch2_name` varchar(30) DEFAULT NULL,
  MODIFY `pitch3_name` varchar(30) DEFAULT NULL,
  MODIFY `pitch4_name` varchar(30) DEFAULT NULL,
  MODIFY `pitch5_name` varchar(30) DEFAULT NULL,

  -- All 26 _pot columns: VARCHAR(255) → VARCHAR(3)
  MODIFY `contact_pot` varchar(3) DEFAULT NULL,
  MODIFY `power_pot` varchar(3) DEFAULT NULL,
  MODIFY `eye_pot` varchar(3) DEFAULT NULL,
  MODIFY `discipline_pot` varchar(3) DEFAULT NULL,
  MODIFY `speed_pot` varchar(3) DEFAULT NULL,
  MODIFY `baserunning_pot` varchar(3) DEFAULT NULL,
  MODIFY `basereaction_pot` varchar(3) DEFAULT NULL,
  MODIFY `fieldcatch_pot` varchar(3) DEFAULT NULL,
  MODIFY `fieldreact_pot` varchar(3) DEFAULT NULL,
  MODIFY `fieldspot_pot` varchar(3) DEFAULT NULL,
  MODIFY `throwpower_pot` varchar(3) DEFAULT NULL,
  MODIFY `throwacc_pot` varchar(3) DEFAULT NULL,
  MODIFY `catchframe_pot` varchar(3) DEFAULT NULL,
  MODIFY `catchsequence_pot` varchar(3) DEFAULT NULL,
  MODIFY `pendurance_pot` varchar(3) DEFAULT NULL,
  MODIFY `pgencontrol_pot` varchar(3) DEFAULT NULL,
  MODIFY `pickoff_pot` varchar(3) DEFAULT NULL,
  MODIFY `psequencing_pot` varchar(3) DEFAULT NULL,
  MODIFY `pthrowpower_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch1_consist_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch1_pacc_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch1_pbrk_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch1_pcntrl_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch2_consist_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch2_pacc_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch2_pbrk_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch2_pcntrl_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch3_consist_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch3_pacc_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch3_pbrk_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch3_pcntrl_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch4_consist_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch4_pacc_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch4_pbrk_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch4_pcntrl_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch5_consist_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch5_pacc_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch5_pbrk_pot` varchar(3) DEFAULT NULL,
  MODIFY `pitch5_pcntrl_pot` varchar(3) DEFAULT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- POST-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'simbbPlayers';

SELECT id, firstname, lastname, bat_hand, pitch_hand, durability, contact_pot, power_pot, ptype
FROM simbbPlayers ORDER BY id DESC LIMIT 10;

ANALYZE TABLE simbbPlayers;
