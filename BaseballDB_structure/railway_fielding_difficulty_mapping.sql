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
-- Table structure for table `fielding_difficulty_mapping`
--

DROP TABLE IF EXISTS `fielding_difficulty_mapping`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `fielding_difficulty_mapping` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `field_zone_id` int unsigned NOT NULL,
  `distance_zone_id` int unsigned NOT NULL,
  `difficulty_level_id` int unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_difficulty` (`field_zone_id`,`distance_zone_id`),
  KEY `distance_zone_id` (`distance_zone_id`),
  KEY `difficulty_level_id` (`difficulty_level_id`),
  KEY `idx_fielding_difficulty_full` (`field_zone_id`,`distance_zone_id`),
  CONSTRAINT `fielding_difficulty_mapping_ibfk_1` FOREIGN KEY (`field_zone_id`) REFERENCES `field_zones` (`id`),
  CONSTRAINT `fielding_difficulty_mapping_ibfk_2` FOREIGN KEY (`distance_zone_id`) REFERENCES `distance_zones` (`id`),
  CONSTRAINT `fielding_difficulty_mapping_ibfk_3` FOREIGN KEY (`difficulty_level_id`) REFERENCES `fielding_difficulty_levels` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=84 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `fielding_difficulty_mapping`
--

LOCK TABLES `fielding_difficulty_mapping` WRITE;
/*!40000 ALTER TABLE `fielding_difficulty_mapping` DISABLE KEYS */;
INSERT INTO `fielding_difficulty_mapping` VALUES (1,3,6,1),(2,3,9,1),(3,5,6,1),(4,5,9,1),(5,4,8,1),(6,4,3,1),(7,4,9,1),(8,1,6,1),(9,1,9,1),(10,7,6,1),(11,7,9,1),(12,2,3,1),(13,2,9,1),(14,6,3,1),(15,6,9,1),(16,3,7,2),(17,3,8,2),(18,3,5,2),(19,5,7,2),(20,5,8,2),(21,5,5,2),(22,4,7,2),(23,4,6,2),(24,1,7,2),(25,1,5,2),(26,7,7,2),(27,7,8,2),(28,7,5,2),(29,2,7,2),(30,2,8,2),(31,2,6,2),(32,6,7,2),(33,6,8,2),(34,6,6,2),(47,3,3,3),(48,5,3,3),(49,4,4,3),(50,4,2,3),(51,4,5,3),(52,1,3,3),(53,7,3,3),(54,2,4,3),(55,2,2,3),(56,2,5,3),(57,6,4,3),(58,6,2,3),(59,6,5,3),(62,3,4,4),(63,3,2,4),(64,5,4,4),(65,5,2,4),(66,1,4,4),(67,1,2,4),(68,7,4,4),(69,7,2,4),(77,3,1,5),(78,5,1,5),(79,4,1,5),(80,1,1,5),(81,7,1,5),(82,2,1,5),(83,6,1,5);
/*!40000 ALTER TABLE `fielding_difficulty_mapping` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:06:09
