-- MySQL dump 10.13  Distrib 8.0.41, for Win64 (x86_64)
--
-- Host: autorack.proxy.rlwy.net    Database: railway
-- ------------------------------------------------------
-- Server version	9.5.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
SET @MYSQLDUMP_TEMP_LOG_BIN = @@SESSION.SQL_LOG_BIN;
SET @@SESSION.SQL_LOG_BIN= 0;

--
-- GTID state at the beginning of the backup 
--

SET @@GLOBAL.GTID_PURGED=/*!80000 '+'*/ '';

--
-- Table structure for table `game_pitching_lines`
--

DROP TABLE IF EXISTS `game_pitching_lines`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `game_pitching_lines` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `game_id` int NOT NULL,
  `player_id` bigint unsigned NOT NULL,
  `team_id` int NOT NULL,
  `pitch_appearance_order` smallint NOT NULL DEFAULT '0',
  `league_year_id` int NOT NULL,
  `games_started` int NOT NULL DEFAULT '0',
  `win` int NOT NULL DEFAULT '0',
  `loss` int NOT NULL DEFAULT '0',
  `save_recorded` int NOT NULL DEFAULT '0',
  `hold` int NOT NULL DEFAULT '0',
  `blown_save` int NOT NULL DEFAULT '0',
  `quality_start` int NOT NULL DEFAULT '0',
  `innings_pitched_outs` int NOT NULL DEFAULT '0',
  `hits_allowed` int NOT NULL DEFAULT '0',
  `runs_allowed` int NOT NULL DEFAULT '0',
  `earned_runs` int NOT NULL DEFAULT '0',
  `walks` int NOT NULL DEFAULT '0',
  `strikeouts` int NOT NULL DEFAULT '0',
  `home_runs_allowed` int NOT NULL DEFAULT '0',
  `pitches_thrown` int NOT NULL DEFAULT '0',
  `balls` int NOT NULL DEFAULT '0',
  `strikes` int NOT NULL DEFAULT '0',
  `hbp` int NOT NULL DEFAULT '0',
  `wildpitches` int NOT NULL DEFAULT '0',
  `inside_the_park_hr_allowed` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_game_pitching` (`game_id`,`player_id`),
  KEY `idx_gpl_player` (`player_id`,`league_year_id`),
  CONSTRAINT `fk_gpl_game` FOREIGN KEY (`game_id`) REFERENCES `gamelist` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=174623 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;
SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-03-17 10:15:56
