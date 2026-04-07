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
-- Table structure for table `time_to_ground`
--

DROP TABLE IF EXISTS `time_to_ground`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `time_to_ground` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `contact_type_id` int unsigned NOT NULL,
  `distance_zone_id` int unsigned NOT NULL,
  `time_value` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_time` (`contact_type_id`,`distance_zone_id`),
  KEY `distance_zone_id` (`distance_zone_id`),
  KEY `idx_time_to_ground_full` (`contact_type_id`,`distance_zone_id`),
  CONSTRAINT `time_to_ground_ibfk_1` FOREIGN KEY (`contact_type_id`) REFERENCES `contact_types` (`id`),
  CONSTRAINT `time_to_ground_ibfk_2` FOREIGN KEY (`distance_zone_id`) REFERENCES `distance_zones` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=31 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `time_to_ground`
--

LOCK TABLES `time_to_ground` WRITE;
/*!40000 ALTER TABLE `time_to_ground` DISABLE KEYS */;
INSERT INTO `time_to_ground` VALUES (1,1,2,2),(2,1,3,1),(3,1,4,1),(4,2,2,3),(5,2,3,2),(6,2,4,1),(7,2,5,1),(8,2,6,1),(9,3,3,3),(10,3,4,2),(11,3,5,2),(12,3,6,1),(13,3,7,1),(14,4,4,3),(15,4,5,2),(16,4,6,1),(17,4,7,1),(18,5,4,4),(19,5,5,3),(20,5,6,2),(21,5,7,1),(22,5,8,1),(23,5,9,1),(24,6,6,1),(25,6,7,1),(26,6,8,1),(27,6,9,1),(28,7,7,1),(29,7,8,1),(30,7,9,1);
/*!40000 ALTER TABLE `time_to_ground` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:12:21
