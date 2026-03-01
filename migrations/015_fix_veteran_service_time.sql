-- Migration 015: Set 6 service years for all MLB players with salary > $800K
--
-- Problem: Migration 012 seeded service time in age-based tiers (3/4/5/6)
-- for players with salary > $800K at MLB level. This caused some veterans
-- to be arb-eligible (3-5 years) instead of FA-eligible (6 years).
--
-- Fix: All MLB-level players earning above the pre-arb salary ($800K) should
-- have 6 service years, making them fa_eligible and ensuring they become
-- free agents when their contracts end.

UPDATE player_service_time pst
JOIN contracts c ON c.playerID = pst.player_id
JOIN contractDetails d ON d.contractID = c.id AND d.year = c.current_year
SET pst.mlb_service_years = 6
WHERE c.isFinished = 0
  AND c.current_level = 9
  AND d.salary > 800000;
