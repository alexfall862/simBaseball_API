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
-- Table structure for table `recruiting_config`
--

DROP TABLE IF EXISTS `recruiting_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `recruiting_config` (
  `id` int NOT NULL AUTO_INCREMENT,
  `config_key` varchar(64) NOT NULL,
  `config_value` varchar(255) NOT NULL,
  `description` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_rc_key` (`config_key`)
) ENGINE=InnoDB AUTO_INCREMENT=18 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `recruiting_config`
--

LOCK TABLES `recruiting_config` WRITE;
/*!40000 ALTER TABLE `recruiting_config` DISABLE KEYS */;
INSERT INTO `recruiting_config` VALUES (1,'points_per_week','100','Recruiting points each school gets per week'),(2,'max_points_per_player_per_week','20','Maximum points investable in one player per week'),(3,'recruiting_weeks','20','Total weeks in recruiting window'),(4,'lottery_exponent','1.3','Superlinear exponent for lottery weighting'),(5,'snipe_threshold_pct','0.80','New school must reach this % of leader to trigger anti-snipe'),(6,'snipe_cooldown_weeks','2','Weeks a new contender must wait before commitment can fire'),(7,'snipe_threshold_mult','1.3','Threshold multiplier when anti-snipe triggers'),(8,'star5_base','300','Base commitment threshold for 5-star'),(9,'star5_decay','12','Weekly threshold decay for 5-star'),(10,'star4_base','200','Base commitment threshold for 4-star'),(11,'star4_decay','8','Weekly threshold decay for 4-star'),(12,'star3_base','120','Base commitment threshold for 3-star'),(13,'star3_decay','5','Weekly threshold decay for 3-star'),(14,'star2_base','60','Base commitment threshold for 2-star'),(15,'star2_decay','2.5','Weekly threshold decay for 2-star'),(16,'star1_base','20','Base commitment threshold for 1-star'),(17,'star1_decay','1','Weekly threshold decay for 1-star');
/*!40000 ALTER TABLE `recruiting_config` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:10:17
