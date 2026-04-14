-- Rebalance pro scouting costs and MLB budget.
-- Precise attributes are cheap, precise potentials are a real commitment.

UPDATE scouting_config SET config_value = '10'   WHERE config_key = 'pro_attrs_precise_cost';
UPDATE scouting_config SET config_value = '50'   WHERE config_key = 'pro_potential_precise_cost';
UPDATE scouting_config SET config_value = '2000' WHERE config_key = 'mlb_budget_per_year';
