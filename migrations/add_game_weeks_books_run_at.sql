-- Add books_run_at to game_weeks so run_week_books() can claim a week
-- atomically instead of relying on a TOCTOU count guard.
--
-- The new claim pattern (in financials/books.py):
--   UPDATE game_weeks SET books_run_at = NOW()
--   WHERE id = :gw_id AND books_run_at IS NULL
-- If rowcount == 0 the week is already claimed and run_week_books returns
-- 'already_processed'. Single-statement atomic, so concurrent callers
-- coming from /admin/run-week-books, run_all_levels, or advance_week can
-- no longer both pass the guard and double-insert ledger rows.
--
-- Backfill: any game_week that already has salary/performance ledger
-- entries is treated as previously processed.
--
-- Idempotent: ADD COLUMN is wrapped in an information_schema check so a
-- partial prior run can be safely retried. The backfill is naturally
-- idempotent via COALESCE.

SET SQL_SAFE_UPDATES = 0;

-- ---- ADD COLUMN (idempotent) ----

SET @sql := IF(
    (SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'game_weeks'
       AND COLUMN_NAME = 'books_run_at') = 0,
    'ALTER TABLE game_weeks ADD COLUMN books_run_at DATETIME NULL DEFAULT NULL AFTER label',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---- BACKFILL ----

UPDATE game_weeks gw
JOIN (
    SELECT DISTINCT game_week_id
    FROM org_ledger_entries
    WHERE game_week_id IS NOT NULL
      AND entry_type IN ('salary', 'performance')
) ran ON ran.game_week_id = gw.id
SET gw.books_run_at = COALESCE(gw.books_run_at, gw.created_at);

SET SQL_SAFE_UPDATES = 1;
