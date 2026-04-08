-- Migration: Hybrid Auto-Draft System
-- Adds round mode configuration, team preferences, and player queue tables.

-- 1. New table: round modes (live vs auto per round)
CREATE TABLE IF NOT EXISTS `draft_round_modes` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_year_id` int NOT NULL,
  `round` int NOT NULL,
  `mode` enum('live','auto') NOT NULL DEFAULT 'live',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_drm_year_round` (`league_year_id`, `round`),
  CONSTRAINT `fk_drm_state` FOREIGN KEY (`league_year_id`)
    REFERENCES `draft_state` (`league_year_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 2. New table: team auto-draft preferences (pitcher/hitter quotas)
CREATE TABLE IF NOT EXISTS `draft_team_prefs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_year_id` int NOT NULL,
  `org_id` int NOT NULL,
  `pitcher_quota` int NOT NULL DEFAULT 0,
  `hitter_quota` int NOT NULL DEFAULT 0,
  `locked` tinyint NOT NULL DEFAULT 0,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dtp_year_org` (`league_year_id`, `org_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 3. New table: player queue (ordered wish list per org)
CREATE TABLE IF NOT EXISTS `draft_player_queue` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_year_id` int NOT NULL,
  `org_id` int NOT NULL,
  `player_id` int NOT NULL,
  `priority` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dpq_year_org_player` (`league_year_id`, `org_id`, `player_id`),
  UNIQUE KEY `uq_dpq_year_org_priority` (`league_year_id`, `org_id`, `priority`),
  KEY `idx_dpq_org_priority` (`league_year_id`, `org_id`, `priority`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 4. Add lock flag to draft_state
ALTER TABLE `draft_state`
  ADD COLUMN `auto_rounds_locked` tinyint NOT NULL DEFAULT 0 AFTER `paused_remaining_s`;
