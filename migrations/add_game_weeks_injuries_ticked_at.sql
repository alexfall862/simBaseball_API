-- Add injuries_ticked_at to game_weeks so _tick_injuries() can claim a week
-- atomically and never decrement the same week's injuries twice.
--
-- Before this, _tick_injuries had no idempotency guard and ran from two
-- independent flows for the same week: advance_week() and the all-levels
-- season runner (games/__init__.py). If both processed one week, every active
-- injury's weeks_remaining was decremented twice — players healed early and
-- career-injury records could fire prematurely (MLB-18/19/29).
--
-- The new claim pattern (in services/timestamp.py):
--   UPDATE game_weeks SET injuries_ticked_at = NOW()
--   WHERE id = :gw_id AND injuries_ticked_at IS NULL
-- If rowcount == 0 the week's tick is already claimed and _tick_injuries
-- returns without decrementing. Single-statement atomic, so concurrent or
-- repeated callers can no longer double-tick.
--
-- Backfill: weeks whose financial books already ran (books_run_at set) have
-- already been advanced, so their injuries have already been ticked — mark
-- them claimed so this guard doesn't re-tick historical weeks.
--
-- Idempotent: ADD COLUMN is wrapped in an information_schema check so a
-- partial prior run can be safely retried. The backfill is idempotent via
-- COALESCE.

SET SQL_SAFE_UPDATES = 0;

-- ---- ADD COLUMN (idempotent) ----

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'game_weeks'
       AND COLUMN_NAME = 'injuries_ticked_at') = 0,
    'ALTER TABLE game_weeks ADD COLUMN injuries_ticked_at DATETIME NULL DEFAULT NULL AFTER books_run_at',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---- BACKFILL ----

-- Any week whose books already ran has already been advanced/ticked.
UPDATE game_weeks gw
SET gw.injuries_ticked_at = COALESCE(gw.injuries_ticked_at, gw.books_run_at)
WHERE gw.books_run_at IS NOT NULL;

SET SQL_SAFE_UPDATES = 1;
