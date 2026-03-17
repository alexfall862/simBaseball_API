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
-- Table structure for table `batting_lab_results`
--

DROP TABLE IF EXISTS `batting_lab_results`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `batting_lab_results` (
  `id` int NOT NULL AUTO_INCREMENT,
  `run_id` int NOT NULL,
  `scenario_key` varchar(64) NOT NULL,
  `tier_label` varchar(32) NOT NULL DEFAULT '',
  `games_played` int NOT NULL DEFAULT '0',
  `plate_appearances` int NOT NULL DEFAULT '0',
  `at_bats` int NOT NULL DEFAULT '0',
  `hits` int NOT NULL DEFAULT '0',
  `doubles_ct` int NOT NULL DEFAULT '0',
  `triples_ct` int NOT NULL DEFAULT '0',
  `home_runs` int NOT NULL DEFAULT '0',
  `walks` int NOT NULL DEFAULT '0',
  `strikeouts` int NOT NULL DEFAULT '0',
  `runs` int NOT NULL DEFAULT '0',
  `rbi` int NOT NULL DEFAULT '0',
  `stolen_bases` int NOT NULL DEFAULT '0',
  `avg_score_home` float NOT NULL DEFAULT '0',
  `avg_score_away` float NOT NULL DEFAULT '0',
  `raw_json` json DEFAULT NULL,
  `inside_the_park_hr` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_blr_run_scenario` (`run_id`,`scenario_key`),
  CONSTRAINT `fk_blr_run` FOREIGN KEY (`run_id`) REFERENCES `batting_lab_runs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
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

-- Dump completed on 2026-03-17 10:17:38
