-- Add per-phase claim columns to league_years so the year-level financial
-- routines (run_year_start_books media + bonuses, process_playoff_revenue,
-- run_year_end_interest) can serialize concurrent callers atomically the
-- same way game_weeks.books_run_at does for run_week_books.
--
-- Each routine claims its column via:
--   UPDATE league_years SET <col> = NOW()
--   WHERE id = :ly_id AND <col> IS NULL
-- and aborts cleanly if rowcount == 0 (someone else already claimed it).
--
-- Backfill: any league_year that already has the relevant ledger entries
-- is treated as previously processed.

ALTER TABLE league_years
    ADD COLUMN media_run_at         DATETIME NULL DEFAULT NULL AFTER weeks_in_season,
    ADD COLUMN bonuses_run_at       DATETIME NULL DEFAULT NULL AFTER media_run_at,
    ADD COLUMN playoff_revenue_run_at DATETIME NULL DEFAULT NULL AFTER bonuses_run_at,
    ADD COLUMN interest_run_at      DATETIME NULL DEFAULT NULL AFTER playoff_revenue_run_at;

-- Backfill media: any year with at least one media ledger row
UPDATE league_years ly
JOIN (
    SELECT DISTINCT league_year_id
    FROM org_ledger_entries
    WHERE entry_type = 'media' AND game_week_id IS NULL
) m ON m.league_year_id = ly.id
SET ly.media_run_at = COALESCE(ly.media_run_at, ly.created_at);

-- Backfill bonuses: any year with at least one bonus or buyout row
UPDATE league_years ly
JOIN (
    SELECT DISTINCT league_year_id
    FROM org_ledger_entries
    WHERE entry_type IN ('bonus', 'buyout') AND game_week_id IS NULL
) b ON b.league_year_id = ly.id
SET ly.bonuses_run_at = COALESCE(ly.bonuses_run_at, ly.created_at);

-- Backfill playoff revenue: any year with playoff_gate or playoff_media
UPDATE league_years ly
JOIN (
    SELECT DISTINCT league_year_id
    FROM org_ledger_entries
    WHERE entry_type IN ('playoff_gate', 'playoff_media')
) p ON p.league_year_id = ly.id
SET ly.playoff_revenue_run_at = COALESCE(ly.playoff_revenue_run_at, ly.created_at);

-- Backfill interest: any year with interest_income or interest_expense
UPDATE league_years ly
JOIN (
    SELECT DISTINCT league_year_id
    FROM org_ledger_entries
    WHERE entry_type IN ('interest_income', 'interest_expense')
) i ON i.league_year_id = ly.id
SET ly.interest_run_at = COALESCE(ly.interest_run_at, ly.created_at);
