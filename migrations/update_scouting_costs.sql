-- Rebalance scouting costs and college budget.
-- Reports are cheap (browsing tier), fuzzed potentials are the main spend,
-- precise potentials are a real commitment.

UPDATE scouting_config SET config_value = '2'    WHERE config_key = 'hs_report_cost';
UPDATE scouting_config SET config_value = '10'   WHERE config_key = 'recruit_potential_fuzzed_cost';
UPDATE scouting_config SET config_value = '50'   WHERE config_key = 'recruit_potential_precise_cost';
UPDATE scouting_config SET config_value = '2000' WHERE config_key = 'college_budget_per_year';
