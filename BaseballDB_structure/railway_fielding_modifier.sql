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
-- Table structure for table `fielding_modifier`
--

DROP TABLE IF EXISTS `fielding_modifier`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `fielding_modifier` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `ball_type` enum('air','ground') NOT NULL,
  `zone_type` enum('infield','outfield') NOT NULL,
  `fielding_outcome_id` int unsigned NOT NULL,
  `modifier_value` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_modifier` (`ball_type`,`zone_type`,`fielding_outcome_id`),
  KEY `fielding_outcome_id` (`fielding_outcome_id`),
  CONSTRAINT `fielding_modifier_ibfk_1` FOREIGN KEY (`fielding_outcome_id`) REFERENCES `fielding_outcomes` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `fielding_modifier`
--

LOCK TABLES `fielding_modifier` WRITE;
/*!40000 ALTER TABLE `fielding_modifier` DISABLE KEYS */;
INSERT INTO `fielding_modifier` VALUES (1,'air','infield',1,2),(2,'air','infield',2,2),(3,'air','infield',3,3),(4,'air','infield',4,0),(5,'air','outfield',1,3),(6,'air','outfield',2,1),(7,'air','outfield',3,5),(8,'air','outfield',4,2),(9,'ground','infield',1,1),(10,'ground','infield',2,5),(11,'ground','infield',3,1),(12,'ground','infield',4,1),(13,'ground','outfield',1,2),(14,'ground','outfield',2,2),(15,'ground','outfield',3,3),(16,'ground','outfield',4,3);
/*!40000 ALTER TABLE `fielding_modifier` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:06:40
