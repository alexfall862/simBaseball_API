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
-- Table structure for table `game_batting_lines`
--

DROP TABLE IF EXISTS `game_batting_lines`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `game_batting_lines` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `game_id` int NOT NULL,
  `player_id` bigint unsigned NOT NULL,
  `team_id` int NOT NULL,
  `position_code` varchar(4) DEFAULT NULL,
  `batting_order` smallint NOT NULL DEFAULT '0',
  `league_year_id` int NOT NULL,
  `at_bats` int NOT NULL DEFAULT '0',
  `runs` int NOT NULL DEFAULT '0',
  `hits` int NOT NULL DEFAULT '0',
  `doubles_hit` int NOT NULL DEFAULT '0',
  `triples` int NOT NULL DEFAULT '0',
  `home_runs` int NOT NULL DEFAULT '0',
  `rbi` int NOT NULL DEFAULT '0',
  `walks` int NOT NULL DEFAULT '0',
  `strikeouts` int NOT NULL DEFAULT '0',
  `stolen_bases` int NOT NULL DEFAULT '0',
  `caught_stealing` int NOT NULL DEFAULT '0',
  `plate_appearances` int NOT NULL DEFAULT '0',
  `hbp` int NOT NULL DEFAULT '0',
  `inside_the_park_hr` int NOT NULL DEFAULT '0',
  `stamina_cost` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_game_batting` (`game_id`,`player_id`),
  KEY `idx_gbl_player` (`player_id`,`league_year_id`),
  KEY `idx_gbl_ly_game` (`league_year_id`,`game_id`),
  CONSTRAINT `fk_gbl_game` FOREIGN KEY (`game_id`) REFERENCES `gamelist` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2313506 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `game_batting_lines`
--

LOCK TABLES `game_batting_lines` WRITE;
/*!40000 ALTER TABLE `game_batting_lines` DISABLE KEYS */;
/*!40000 ALTER TABLE `game_batting_lines` ENABLE KEYS */;
UNLOCK TABLES;
SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-03-29  0:18:34
