-- =============================================================================
-- Batch 05: org_ledger_entries DECIMAL Right-Sizing
-- *** MAINTENANCE WINDOW — 41M rows, full table rebuild ***
-- Risk: Low (DECIMAL(14,2) supports up to $999 billion)
-- Downtime: Extended rebuild (may take 10-30+ minutes depending on hardware)
-- Estimated savings: ~78 MB
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- PRE-FLIGHT: Verify max amount fits in DECIMAL(14,2) (max 999,999,999,999.99)
-- ─────────────────────────────────────────────────────────────────────────────

SELECT
  MAX(amount) AS max_amount,
  MIN(amount) AS min_amount,
  MAX(ABS(amount)) AS max_abs_amount,
  COUNT(*) AS total_rows
FROM org_ledger_entries;

-- max_abs_amount must be < 1,000,000,000,000 (1 trillion)
-- If it exceeds this, DO NOT proceed — adjust DECIMAL precision accordingly.

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'org_ledger_entries';

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATION
-- amount: DECIMAL(18,2) → DECIMAL(14,2)
-- Byte savings: 9 bytes → 7 bytes = 2 bytes/row × 41M rows = ~78 MB
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE org_ledger_entries
  MODIFY `amount` decimal(14,2) NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- POST-FLIGHT
-- ─────────────────────────────────────────────────────────────────────────────

SELECT TABLE_NAME, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH,
       DATA_LENGTH + INDEX_LENGTH AS total_bytes
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 'org_ledger_entries';

SELECT * FROM org_ledger_entries ORDER BY id DESC LIMIT 5;

ANALYZE TABLE org_ledger_entries;
