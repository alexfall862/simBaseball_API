-- Add min_roster column to levels table and populate values
-- Roster limits: 9-5 (min 20, max 26), 4 (min 0, max 40), 3 (min 25, max 35)

ALTER TABLE `levels` ADD COLUMN `min_roster` int DEFAULT NULL AFTER `league_level`;

-- Set min_roster values
UPDATE `levels` SET `min_roster` = 20 WHERE `id` IN (5, 6, 7, 8, 9);
UPDATE `levels` SET `min_roster` = 0  WHERE `id` = 4;
UPDATE `levels` SET `min_roster` = 25 WHERE `id` = 3;

-- Update max_roster to match new limits (5-8 were 28, now 26; 3 was 40, now 35)
UPDATE `levels` SET `max_roster` = 26 WHERE `id` IN (5, 6, 7, 8);
UPDATE `levels` SET `max_roster` = 35 WHERE `id` = 3;
