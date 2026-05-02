-- One-shot cleanup: deduplicate the week-6 salary/performance entries that
-- were inserted twice when run_week_books fired concurrently before the
-- atomic books_run_at claim was added.
--
-- USAGE:
--   1. Set @league_year / @week_index to the affected season + week.
--   2. Run the SELECTs that resolve @ly_id / @gw_id.
--   3. Run the temp-table population step (step 1) — fast, scoped to one
--      week via the (org_id, league_year_id, game_week_id) index.
--   4. Run the preview SELECT (step 2) to verify the count + sample rows.
--   5. Run the DELETE (step 3). It deletes by primary key, so it's fast
--      and won't time out the connection.
--   6. Run the final UPDATE (step 4) to mark the week as processed.
--
-- Why not a self-join DELETE on org_ledger_entries?
--   The natural-key join (org_id, league_year_id, game_week_id, entry_type,
--   contract_id, amount) isn't covered by any single index on the 41M-row
--   ledger table, so the optimizer falls back to a long scan that exceeds
--   wait_timeout / net_write_timeout. Window function over the week-scoped
--   subset is index-friendly and runs in seconds.

SET @league_year := 2026;
SET @week_index  := 6;

SELECT @ly_id := id FROM league_years WHERE league_year = @league_year;
SELECT @gw_id := id FROM game_weeks
    WHERE league_year_id = @ly_id AND week_index = @week_index;

-- ---------------------------------------------------------------
-- Step 1: collect surplus IDs into a temp table.
-- ROW_NUMBER() = 1 keeps the lowest id per natural-key tuple;
-- everything > 1 is a duplicate to delete.
-- ---------------------------------------------------------------
DROP TEMPORARY TABLE IF EXISTS week6_dupes;
CREATE TEMPORARY TABLE week6_dupes (
    id BIGINT NOT NULL PRIMARY KEY
) ENGINE=InnoDB;

INSERT INTO week6_dupes (id)
SELECT id FROM (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY
                org_id,
                league_year_id,
                game_week_id,
                entry_type,
                COALESCE(contract_id, 0),
                amount
            ORDER BY id
        ) AS rn
    FROM org_ledger_entries
    WHERE game_week_id   = @gw_id
      AND league_year_id = @ly_id
      AND entry_type IN ('salary', 'performance')
) t
WHERE rn > 1;

-- ---------------------------------------------------------------
-- Step 2: preview — how many rows, and a sample.
-- ---------------------------------------------------------------
SELECT COUNT(*) AS surplus_rows FROM week6_dupes;

SELECT l.id, l.org_id, l.entry_type, l.amount, l.contract_id, l.note, l.created_at
FROM org_ledger_entries l
JOIN week6_dupes d ON d.id = l.id
ORDER BY l.org_id, l.entry_type, l.contract_id, l.id
LIMIT 50;

-- ---------------------------------------------------------------
-- Step 3: delete by primary key. Fast — no self-join scan.
-- If you want to chunk it (e.g. on a slow link), wrap in a loop
-- with LIMIT 5000; the join target is the temp table.
-- ---------------------------------------------------------------
DELETE l FROM org_ledger_entries l
JOIN week6_dupes d ON d.id = l.id;

DROP TEMPORARY TABLE IF EXISTS week6_dupes;

-- ---------------------------------------------------------------
-- Step 4: mark the week as processed so future run_week_books
-- calls short-circuit via the atomic books_run_at claim.
-- ---------------------------------------------------------------
UPDATE game_weeks
SET books_run_at = COALESCE(books_run_at, NOW())
WHERE id = @gw_id;
