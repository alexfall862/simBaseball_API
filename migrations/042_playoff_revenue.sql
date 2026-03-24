-- Migration 042: Playoff Revenue System
--
-- Adds configurable columns to financial_config for:
-- 1. playoff_gate_multiplier  - home game gate revenue = regular per-game value × this
-- 2. playoff_media_fraction   - fraction of media_total allocated to playoff media payouts

ALTER TABLE `financial_config`
  ADD COLUMN `playoff_gate_multiplier` decimal(6,2) NOT NULL DEFAULT 5.00,
  ADD COLUMN `playoff_media_fraction`  decimal(6,4) NOT NULL DEFAULT 0.1000;
