-- Migration: add rating_type column to displayovr_breakpoints
-- Supports per-position breakpoints (c_rating, sp_rating, etc.)
-- alongside the existing 'displayovr' breakpoints.
--
-- Safe to run multiple times (checks for column existence).

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'displayovr_breakpoints'
      AND COLUMN_NAME = 'rating_type'
);

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE displayovr_breakpoints
         ADD COLUMN rating_type VARCHAR(32) NOT NULL DEFAULT ''displayovr'',
         DROP PRIMARY KEY,
         ADD PRIMARY KEY (level, ptype, rating_type)',
    'SELECT ''rating_type column already exists'' AS info');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
