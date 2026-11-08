-- Season 2 feature schema: graduation / amateur pipeline, retirements, draft
-- bonus negotiation, draft trade proposals, end-of-FA fallback deals, and
-- the two config tables (league_config, fa_config).
--
-- Apply ONCE to the live database, after the four earlier migrations
-- (seed_financial_config, seed_draft_slot_values, add_draft_picks_player_unique,
-- normalize_finished_contracts_inactive). The ALTER TABLE statements are not
-- idempotent; the CREATE TABLE / INSERT IGNORE statements are.

-- ── league_config: tunable sizes and thresholds for the amateur pipeline ──
CREATE TABLE IF NOT EXISTS league_config (
  config_key   VARCHAR(64)  NOT NULL,
  config_value VARCHAR(64)  NOT NULL,
  description  VARCHAR(255) NULL,
  PRIMARY KEY (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO league_config (config_key, config_value, description) VALUES
  ('hs_pool_target',        '8864', 'Total US high-school players kept in the pool; freshmen are generated at end-season to refill it'),
  ('hs_entry_age',          '15',   'Age of generated HS freshmen (after the end-season age bump)'),
  ('intam_pool_target',     '6722', 'Total international amateur (INTAM) players kept in the pool'),
  ('intam_entry_age',       '15',   'Age of generated INTAM entrants'),
  ('intam_age_out',         '23',   'INTAM players leave the pool (become free agents) at this age'),
  ('college_roster_floor',  '25',   'Colleges below this roster size are topped up with generated walk-ons after the draft'),
  ('college_roster_target', '28',   'Undrafted HS graduates are placed at random on programs below this roster size; the surplus retires'),
  ('undrafted_keep_ovr',    '65',   'Undrafted college seniors / aged-out INTAM players stay in the FA pool at or above this displayovr; below it they retire'),
  ('never_signed_retire_age','25',  'Unsigned players who never held a pro contract retire at this age'),
  ('walkon_age',            '19',   'Age of generated college walk-ons'),
  ('retire_age_hard',       '0',    'Players at or above this age retire regardless of contract; 0 disables the rule'),
  ('retire_age_unsigned',   '36',   'Players at or above this age with no active pro contract retire'),
  ('retire_age_marginal',   '33',   'Players at or above this age, unsigned and below retire_marginal_ovr, retire'),
  ('retire_marginal_ovr',   '40',   'displayovr threshold for the marginal-retirement rule');

-- ── fa_config: pricing / end-of-FA constants ──
CREATE TABLE IF NOT EXISTS fa_config (
  config_key   VARCHAR(64)  NOT NULL,
  config_value VARCHAR(64)  NOT NULL,
  description  VARCHAR(255) NULL,
  PRIMARY KEY (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO fa_config (config_key, config_value, description) VALUES
  ('dollar_per_war_default', '8000000',  'Bootstrap $/WAR when there is too little market history'),
  ('dollar_per_war_min',     '4000000',  'Lower clamp on the market $/WAR'),
  ('dollar_per_war_max',     '15000000', 'Upper clamp on the market $/WAR'),
  ('market_min_history',     '5',        'Signings needed before the market rate is used unblended'),
  ('market_lookback_years',  '3',        'Rolling window (league years) for the market rate'),
  ('market_extension_weight','0.9',      'Weight of extension signings in the market sample (arb renewals are excluded)'),
  ('war_blend_w0',           '0.5',      'Demand WAR weight: most recent season'),
  ('war_blend_w1',           '0.3',      'Demand WAR weight: one season back'),
  ('war_blend_w2',           '0.2',      'Demand WAR weight: two seasons back'),
  ('war_regress_pa',         '200',      'Plate appearances below which a season WAR is regressed toward 0'),
  ('war_regress_ip',         '50',       'Innings pitched below which a season WAR is regressed toward 0'),
  ('fa_fallback_mlb_level',  '8',        'Level of the fallback deal for an unsigned MLB free agent (AAA)'),
  ('fa_fallback_minor_level','4',        'Level of the fallback deal for an unsigned minor-league free agent');

-- ── Retirements ──
CREATE TABLE IF NOT EXISTS player_retirements (
  id             INT NOT NULL AUTO_INCREMENT,
  player_id      INT NOT NULL,
  league_year_id INT NOT NULL COMMENT 'season after which the player retired',
  age            INT NOT NULL,
  reason         VARCHAR(32) NOT NULL,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_retire_player (player_id),
  KEY idx_retire_year (league_year_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Draft pool: class year and composite kept with the snapshot ──
ALTER TABLE draft_eligible_players
  ADD COLUMN class_year VARCHAR(16) NULL AFTER source,
  ADD COLUMN composite  DECIMAL(10,4) NULL AFTER draft_rank;

-- ── Draft signing negotiation ──
ALTER TABLE draft_signing
  ADD COLUMN ask_bonus    DECIMAL(12,2) NULL     AFTER slot_value,
  ADD COLUMN class_year   VARCHAR(16)   NULL     AFTER ask_bonus,
  ADD COLUMN willingness  DECIMAL(4,2)  NULL     AFTER class_year,
  ADD COLUMN offers_made  INT NOT NULL DEFAULT 0 AFTER willingness,
  ADD COLUMN bonus_agreed DECIMAL(12,2) NULL     AFTER offers_made,
  ADD COLUMN resolved_at  DATETIME      NULL     AFTER signed_at;

CREATE TABLE IF NOT EXISTS draft_signing_offers (
  id            INT NOT NULL AUTO_INCREMENT,
  draft_pick_id INT NOT NULL,
  offer_no      INT NOT NULL,
  amount        DECIMAL(12,2) NOT NULL,
  accept_prob   DECIMAL(6,4) NOT NULL,
  roll          DECIMAL(6,4) NOT NULL,
  result        ENUM('accepted','rejected') NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_dso_pick_no (draft_pick_id, offer_no),
  CONSTRAINT fk_dso_pick FOREIGN KEY (draft_pick_id) REFERENCES draft_picks (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Draft pick trade proposals (interface: draft/trade/propose|proposals|accept|reject) ──
CREATE TABLE IF NOT EXISTS draft_trade_proposals (
  id               INT NOT NULL AUTO_INCREMENT,
  league_year_id   INT NOT NULL,
  proposing_org_id INT NOT NULL,
  receiving_org_id INT NOT NULL,
  picks_offered    JSON NOT NULL,
  picks_requested  JSON NOT NULL,
  status           ENUM('proposed','accepted','rejected','cancelled') NOT NULL DEFAULT 'proposed',
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at      DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_dtp_year_status (league_year_id, status),
  KEY idx_dtp_receiving (receiving_org_id, status),
  KEY idx_dtp_proposing (proposing_org_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── End-of-FA fallback deals ──
ALTER TABLE contracts
  ADD COLUMN fa_fallback TINYINT NOT NULL DEFAULT 0 AFTER onIR;

ALTER TABLE fa_auction
  MODIFY COLUMN phase ENUM('open','listening','finalize','completed','withdrawn','expired') NOT NULL DEFAULT 'open';

-- ── New transaction types written by the pipeline ──
ALTER TABLE transaction_log
  MODIFY COLUMN transaction_type ENUM(
    'trade','release','signing','extension','buyout','promote','demote',
    'ir_place','ir_activate','renewal','draft_sign','draft_pick_trade',
    'fa_offer','fa_offer_update','fa_auction_sign','arb_renewal',
    'waiver_place','waiver_claim','ifa_offer','ifa_offer_update','ifa_signing',
    'scouting_purchase',
    'college_enroll','walkon_enroll','retirement','fa_fallback','draft_refused'
  ) NOT NULL;
