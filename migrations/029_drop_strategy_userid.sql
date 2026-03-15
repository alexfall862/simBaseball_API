-- Migration 029: Remove userID from playerStrategies unique key
--
-- playerStrategies was keyed on (playerID, orgID, userID) but strategies
-- are org-level, not per-user.  The userID column caused FK errors when
-- the frontend could not resolve the current user, and the game engine
-- never reads it.
--
-- Steps:
--   1. Drop the FK constraint on userID
--   2. Drop the old unique key (playerID, orgID, userID)
--   3. De-duplicate: keep only the newest row per (playerID, orgID)
--   4. Create new unique key (playerID, orgID)
--   5. Make userID nullable (keep column for audit trail)

-- 1. Drop FK
ALTER TABLE `playerStrategies` DROP FOREIGN KEY `fk_user_strategy`;

-- 2. Drop old unique key
ALTER TABLE `playerStrategies` DROP INDEX `pouIndex`;

-- 3. De-duplicate: if multiple rows exist for the same (playerID, orgID),
--    keep the one with the highest id (most recent upsert)
DELETE ps1
FROM `playerStrategies` ps1
INNER JOIN `playerStrategies` ps2
  ON ps1.playerID = ps2.playerID
 AND ps1.orgID = ps2.orgID
 AND ps1.id < ps2.id;

-- 4. New unique key without userID
ALTER TABLE `playerStrategies` ADD UNIQUE KEY `uq_player_org` (`playerID`, `orgID`);

-- 5. Make userID nullable
ALTER TABLE `playerStrategies` MODIFY COLUMN `userID` int DEFAULT NULL;
