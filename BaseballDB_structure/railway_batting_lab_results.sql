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

--
-- Dumping data for table `batting_lab_results`
--

LOCK TABLES `batting_lab_results` WRITE;
/*!40000 ALTER TABLE `batting_lab_results` DISABLE KEYS */;
INSERT INTO `batting_lab_results` VALUES (1,1,'tier_elite','elite',50,5757,4976,2708,903,1060,298,781,267,2741,2676,181,27.12,27.7,'{\"avg\": 0.544, \"iso\": 0.787, \"obp\": 0.606, \"ops\": 1.937, \"slg\": 1.331, \"k_pct\": 4.6, \"bb_pct\": 13.6}',0),(2,1,'tier_above_avg','above_avg',50,3495,3082,568,115,104,138,413,290,551,541,62,5.52,5.5,'{\"avg\": 0.184, \"iso\": 0.239, \"obp\": 0.281, \"ops\": 0.704, \"slg\": 0.423, \"k_pct\": 8.3, \"bb_pct\": 11.8}',0),(3,1,'tier_average','average',50,3703,3345,845,347,31,28,358,583,370,360,77,4.04,3.36,'{\"avg\": 0.253, \"iso\": 0.147, \"obp\": 0.325, \"ops\": 0.725, \"slg\": 0.4, \"k_pct\": 15.7, \"bb_pct\": 9.7}',0),(4,1,'tier_below_avg','below_avg',50,3750,3453,696,188,21,22,297,807,178,167,73,1.7,1.86,'{\"avg\": 0.202, \"iso\": 0.086, \"obp\": 0.265, \"ops\": 0.552, \"slg\": 0.287, \"k_pct\": 21.5, \"bb_pct\": 7.9}',0),(5,1,'tier_poor','poor',50,4513,4211,599,170,7,7,302,1183,78,67,52,0.46,1.1,'{\"avg\": 0.142, \"iso\": 0.049, \"obp\": 0.2, \"ops\": 0.391, \"slg\": 0.191, \"k_pct\": 26.2, \"bb_pct\": 6.7}',0);
/*!40000 ALTER TABLE `batting_lab_results` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:15:06
