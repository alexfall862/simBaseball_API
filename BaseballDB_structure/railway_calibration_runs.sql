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
-- Table structure for table `calibration_runs`
--

DROP TABLE IF EXISTS `calibration_runs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `calibration_runs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `profile_id` int NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `config_json` text,
  `results_json` text,
  PRIMARY KEY (`id`),
  KEY `fk_cr_profile` (`profile_id`),
  CONSTRAINT `fk_cr_profile` FOREIGN KEY (`profile_id`) REFERENCES `weight_profiles` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `calibration_runs`
--

LOCK TABLES `calibration_runs` WRITE;
/*!40000 ALTER TABLE `calibration_runs` DISABLE KEYS */;
INSERT INTO `calibration_runs` VALUES (1,1,'2026-03-16 05:50:38','{\"min_innings\": 100, \"min_ipo\": 100, \"name\": \"Test Calibration\"}','{\"c_rating\": {\"rating_type\": \"c_rating\", \"position_code\": \"c\", \"n\": 41, \"offense_r2\": 0.5764, \"defense_r2\": 0.2658, \"warnings\": [\"catchframe_base: negative beta (-0.114) \\u2014 attribute may hurt performance at this position\", \"catchsequence_base: negative beta (-0.410) \\u2014 attribute may hurt performance at this position\"]}, \"fb_rating\": {\"rating_type\": \"fb_rating\", \"position_code\": \"fb\", \"n\": 61, \"offense_r2\": 0.3914, \"defense_r2\": 0.3316, \"warnings\": [\"baserunning_base: negative beta (-0.226) \\u2014 attribute may hurt performance at this position\", \"throwpower_base: negative beta (-0.110) \\u2014 attribute may hurt performance at this position\"]}, \"sb_rating\": {\"rating_type\": \"sb_rating\", \"position_code\": \"sb\", \"n\": 57, \"offense_r2\": 0.3504, \"defense_r2\": 0.3321, \"warnings\": [\"fieldspot_base: negative beta (-0.147) \\u2014 attribute may hurt performance at this position\"]}, \"tb_rating\": {\"rating_type\": \"tb_rating\", \"position_code\": \"tb\", \"n\": 59, \"offense_r2\": 0.2675, \"defense_r2\": 0.1461, \"warnings\": [\"baserunning_base: negative beta (-0.110) \\u2014 attribute may hurt performance at this position\", \"throwpower_base: negative beta (-0.156) \\u2014 attribute may hurt performance at this position\"]}, \"ss_rating\": {\"rating_type\": \"ss_rating\", \"position_code\": \"ss\", \"n\": 48, \"offense_r2\": 0.5576, \"defense_r2\": 0.2385, \"warnings\": [\"baserunning_base: negative beta (-0.164) \\u2014 attribute may hurt performance at this position\", \"fieldcatch_base: negative beta (-0.101) \\u2014 attribute may hurt performance at this position\", \"throwpower_base: negative beta (-0.170) \\u2014 attribute may hurt performance at this position\"]}, \"lf_rating\": {\"rating_type\": \"lf_rating\", \"position_code\": \"lf\", \"n\": 60, \"offense_r2\": 0.2665, \"defense_r2\": 0.2155, \"warnings\": [\"fieldreact_base: negative beta (-0.180) \\u2014 attribute may hurt performance at this position\", \"throwpower_base: negative beta (-0.181) \\u2014 attribute may hurt performance at this position\"]}, \"cf_rating\": {\"rating_type\": \"cf_rating\", \"position_code\": \"cf\", \"n\": 52, \"offense_r2\": 0.383, \"defense_r2\": 0.1354, \"warnings\": [\"basereaction_base: negative beta (-0.168) \\u2014 attribute may hurt performance at this position\", \"throwacc_base: negative beta (-0.118) \\u2014 attribute may hurt performance at this position\", \"throwpower_base: negative beta (-0.315) \\u2014 attribute may hurt performance at this position\"]}, \"rf_rating\": {\"rating_type\": \"rf_rating\", \"position_code\": \"rf\", \"n\": 59, \"offense_r2\": 0.5545, \"defense_r2\": 0.0925, \"warnings\": [\"throwpower_base: negative beta (-0.166) \\u2014 attribute may hurt performance at this position\"]}, \"dh_rating\": {\"rating_type\": \"dh_rating\", \"position_code\": \"dh\", \"n\": 0, \"offense_r2\": null, \"defense_r2\": null, \"warnings\": [\"Insufficient data: 0 players (need 9)\"], \"skipped\": true}, \"sp_rating\": {\"rating_type\": \"sp_rating\", \"position_code\": \"sp\", \"n\": 152, \"r2\": 0.3419, \"warnings\": [\"pgencontrol_base: negative beta (-0.144) \\u2014 attribute may hurt performance at this position\"]}, \"rp_rating\": {\"rating_type\": \"rp_rating\", \"position_code\": \"rp\", \"n\": 83, \"r2\": 0.3674, \"warnings\": [\"fieldreact_base: negative beta (-0.102) \\u2014 attribute may hurt performance at this position\"]}}'),(2,2,'2026-03-16 14:18:41','{\"min_innings\": 50, \"min_ipo\": 60, \"name\": \"Test Calibration 2\"}','{\"c_rating\": {\"rating_type\": \"c_rating\", \"position_code\": \"c\", \"n\": 78, \"confidence_level\": \"high\", \"offense_r2\": 0.6934, \"offense_adj_r2\": 0.6627, \"defense_r2\": 0.2563, \"defense_adj_r2\": 0.1819, \"warnings\": [\"baserunning_base: negative beta (-0.117) \\u2014 attribute may hurt performance at this position\", \"catchsequence_base: negative beta (-0.181) \\u2014 attribute may hurt performance at this position\"]}, \"fb_rating\": {\"rating_type\": \"fb_rating\", \"position_code\": \"fb\", \"n\": 143, \"confidence_level\": \"high\", \"offense_r2\": 0.3388, \"offense_adj_r2\": 0.3045, \"defense_r2\": 0.1933, \"defense_adj_r2\": 0.1638, \"warnings\": []}, \"sb_rating\": {\"rating_type\": \"sb_rating\", \"position_code\": \"sb\", \"n\": 127, \"confidence_level\": \"high\", \"offense_r2\": 0.4206, \"offense_adj_r2\": 0.3865, \"defense_r2\": 0.2097, \"defense_adj_r2\": 0.1771, \"warnings\": [\"fieldspot_base: negative beta (-0.177) \\u2014 attribute may hurt performance at this position\"]}, \"tb_rating\": {\"rating_type\": \"tb_rating\", \"position_code\": \"tb\", \"n\": 113, \"confidence_level\": \"high\", \"offense_r2\": 0.3781, \"offense_adj_r2\": 0.3366, \"defense_r2\": 0.1056, \"defense_adj_r2\": 0.0638, \"warnings\": [\"throwpower_base: negative beta (-0.184) \\u2014 attribute may hurt performance at this position\"]}, \"ss_rating\": {\"rating_type\": \"ss_rating\", \"position_code\": \"ss\", \"n\": 94, \"confidence_level\": \"high\", \"offense_r2\": 0.4974, \"offense_adj_r2\": 0.4565, \"defense_r2\": 0.2583, \"defense_adj_r2\": 0.2161, \"warnings\": [\"baserunning_base: negative beta (-0.116) \\u2014 attribute may hurt performance at this position\", \"throwpower_base: negative beta (-0.280) \\u2014 attribute may hurt performance at this position\"]}, \"lf_rating\": {\"rating_type\": \"lf_rating\", \"position_code\": \"lf\", \"n\": 137, \"confidence_level\": \"high\", \"offense_r2\": 0.3365, \"offense_adj_r2\": 0.3005, \"defense_r2\": 0.0308, \"defense_adj_r2\": -0.0062, \"warnings\": [\"throwpower_base: negative beta (-0.101) \\u2014 attribute may hurt performance at this position\"]}, \"cf_rating\": {\"rating_type\": \"cf_rating\", \"position_code\": \"cf\", \"n\": 106, \"confidence_level\": \"high\", \"offense_r2\": 0.395, \"offense_adj_r2\": 0.3518, \"defense_r2\": 0.1119, \"defense_adj_r2\": 0.0675, \"warnings\": [\"throwpower_base: negative beta (-0.324) \\u2014 attribute may hurt performance at this position\"]}, \"rf_rating\": {\"rating_type\": \"rf_rating\", \"position_code\": \"rf\", \"n\": 139, \"confidence_level\": \"high\", \"offense_r2\": 0.3855, \"offense_adj_r2\": 0.3527, \"defense_r2\": 0.0599, \"defense_adj_r2\": 0.0246, \"warnings\": [\"throwpower_base: negative beta (-0.170) \\u2014 attribute may hurt performance at this position\"]}, \"dh_rating\": {\"rating_type\": \"dh_rating\", \"position_code\": \"dh\", \"n\": 0, \"confidence_level\": \"low\", \"offense_r2\": null, \"offense_adj_r2\": null, \"defense_r2\": null, \"defense_adj_r2\": null, \"warnings\": [\"Insufficient data: 0 players (need 9)\"], \"skipped\": true}, \"sp_rating\": {\"rating_type\": \"sp_rating\", \"position_code\": \"sp\", \"n\": 153, \"confidence_level\": \"high\", \"r2\": 0.4614, \"adj_r2\": 0.4152, \"warnings\": [\"pgencontrol_base: negative beta (-0.187) \\u2014 attribute may hurt performance at this position\"]}, \"rp_rating\": {\"rating_type\": \"rp_rating\", \"position_code\": \"rp\", \"n\": 160, \"confidence_level\": \"high\", \"r2\": 0.322, \"adj_r2\": 0.2666, \"warnings\": []}}');
/*!40000 ALTER TABLE `calibration_runs` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:07:25
