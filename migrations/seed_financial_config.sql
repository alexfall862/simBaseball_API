-- financial_config was never seeded on the live database. It is read by
-- initialize_next_league_year (inflation bounds -> next year's budgets, now
-- called by end-season), run_playoff_revenue (gate multiplier, media
-- fraction) and the year-end interest books. Values mirror league year 2026:
-- budgets 2.46B each, inflation_factor 1.0350, 52 weeks, 5% interest.
INSERT INTO financial_config
    (id, base_performance_budget, base_media_total,
     inflation_min, inflation_max, inflation_mean,
     interest_rate, weeks_per_season,
     playoff_gate_multiplier, playoff_media_fraction)
SELECT 1, ly.performance_budget, ly.media_total,
       0.0200, 0.0500, 0.0350,
       0.0500, ly.weeks_in_season,
       5.00, 0.1000
FROM league_years ly
WHERE ly.league_year = 2026
  AND NOT EXISTS (SELECT 1 FROM financial_config);
