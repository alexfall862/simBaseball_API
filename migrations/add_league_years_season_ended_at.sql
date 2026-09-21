-- End-of-season idempotency claim (mirrors the books_run_at / injuries_ticked_at
-- pattern). services/timestamp.py:end_regular_season adds this column lazily if
-- it is missing, so applying this file by hand is optional but recommended.
--
-- To deliberately re-run end-of-season for a year (NOT normally wanted: it ages
-- every player and expires contracts again):
--   UPDATE league_years SET season_ended_at = NULL WHERE id = <league_year_id>;

ALTER TABLE `league_years`
    ADD COLUMN `season_ended_at` DATETIME NULL DEFAULT NULL;
