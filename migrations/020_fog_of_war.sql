-- Migration 020: Fog-of-war attribute visibility system
-- Expands scouting action types for tiered org-specific attribute fuzzying.
-- Adds new cost configuration entries for each scouting tier.

-- 1. Expand action_type ENUM on scouting_actions
ALTER TABLE scouting_actions
  MODIFY COLUMN action_type ENUM(
    'hs_report',
    'hs_potential',
    'pro_numeric',
    'recruit_potential_fuzzed',
    'recruit_potential_precise',
    'college_potential_precise',
    'draft_attrs_fuzzed',
    'draft_attrs_precise',
    'draft_potential_precise',
    'pro_attrs_precise',
    'pro_potential_precise'
  ) NOT NULL;

-- 2. Migrate existing actions to new type names
--    hs_potential was "full unlock" -> recruit_potential_precise
UPDATE scouting_actions
  SET action_type = 'recruit_potential_precise'
  WHERE action_type = 'hs_potential';

--    pro_numeric was "full unlock" -> draft_attrs_precise
UPDATE scouting_actions
  SET action_type = 'draft_attrs_precise'
  WHERE action_type = 'pro_numeric';

-- 3. Add new scouting config cost entries
INSERT IGNORE INTO scouting_config (config_key, config_value, description) VALUES
  ('recruit_potential_fuzzed_cost', '15',  'Cost: fuzzed potential for HS recruit'),
  ('recruit_potential_precise_cost', '25', 'Cost: precise potential for HS recruit'),
  ('college_potential_precise_cost', '15', 'Cost: precise potential for college player'),
  ('draft_attrs_fuzzed_cost',        '10', 'Cost: fuzzed 20-80 for draft-eligible player'),
  ('draft_attrs_precise_cost',       '20', 'Cost: precise 20-80 for draft-eligible player'),
  ('draft_potential_precise_cost',   '15', 'Cost: precise potential for draft-eligible player'),
  ('pro_attrs_precise_cost',         '15', 'Cost: precise 20-80 for pro roster player'),
  ('pro_potential_precise_cost',     '15', 'Cost: precise potential for pro roster player');

-- 4. Deprecate old config keys (keep for reference)
UPDATE scouting_config
  SET config_key = 'hs_potential_cost_legacy',
      description = 'DEPRECATED: replaced by recruit_potential_fuzzed_cost + recruit_potential_precise_cost'
  WHERE config_key = 'hs_potential_cost';

UPDATE scouting_config
  SET config_key = 'pro_numeric_cost_legacy',
      description = 'DEPRECATED: replaced by draft_attrs_fuzzed_cost + draft_attrs_precise_cost'
  WHERE config_key = 'pro_numeric_cost';

-- 5. Remove legacy values from ENUM now that data is migrated
ALTER TABLE scouting_actions
  MODIFY COLUMN action_type ENUM(
    'hs_report',
    'recruit_potential_fuzzed',
    'recruit_potential_precise',
    'college_potential_precise',
    'draft_attrs_fuzzed',
    'draft_attrs_precise',
    'draft_potential_precise',
    'pro_attrs_precise',
    'pro_potential_precise'
  ) NOT NULL;
