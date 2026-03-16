-- Migration 037: Add percentile breakpoints for derived rating scaling
--
-- Derived ratings (position ratings, overalls) are weighted averages of
-- multiple attributes, which compresses their variance. Z-score based
-- 20-80 scaling preserves this compression, clustering values around 50.
--
-- This column stores percentile breakpoints so derived ratings can use
-- percentile-rank mapping instead, guaranteeing full 20-80 spread.

ALTER TABLE rating_scale_config
  ADD COLUMN percentiles_json JSON DEFAULT NULL;
