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
-- Table structure for table `defensive_alignment`
--

DROP TABLE IF EXISTS `defensive_alignment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `defensive_alignment` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `field_zone_id` int unsigned NOT NULL,
  `distance_zone_id` int unsigned NOT NULL,
  `position_id` int unsigned NOT NULL,
  `priority` int NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_alignment` (`field_zone_id`,`distance_zone_id`,`position_id`),
  KEY `idx_zone_lookup` (`field_zone_id`,`distance_zone_id`),
  KEY `distance_zone_id` (`distance_zone_id`),
  KEY `position_id` (`position_id`),
  KEY `idx_defensive_alignment_full` (`field_zone_id`,`distance_zone_id`,`position_id`),
  CONSTRAINT `defensive_alignment_ibfk_1` FOREIGN KEY (`field_zone_id`) REFERENCES `field_zones` (`id`),
  CONSTRAINT `defensive_alignment_ibfk_2` FOREIGN KEY (`distance_zone_id`) REFERENCES `distance_zones` (`id`),
  CONSTRAINT `defensive_alignment_ibfk_3` FOREIGN KEY (`position_id`) REFERENCES `defensive_positions` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=76 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `defensive_alignment`
--

LOCK TABLES `defensive_alignment` WRITE;
/*!40000 ALTER TABLE `defensive_alignment` DISABLE KEYS */;
INSERT INTO `defensive_alignment` VALUES (1,1,2,7,1),(2,1,3,7,1),(3,1,4,7,1),(4,1,5,5,1),(5,1,6,5,1),(6,1,7,5,1),(7,1,8,5,1),(8,1,8,1,2),(9,1,9,2,1),(10,2,2,7,1),(11,2,3,7,1),(12,2,4,7,1),(13,2,5,6,1),(14,2,6,6,1),(15,2,7,6,1),(16,2,7,5,2),(17,2,8,5,1),(18,2,8,6,2),(19,2,8,1,3),(20,2,9,2,1),(21,3,2,8,1),(22,3,2,7,2),(23,3,3,8,1),(24,3,3,7,2),(25,3,4,8,1),(26,3,4,7,2),(27,3,5,6,1),(28,3,6,6,1),(29,3,7,6,1),(30,3,8,6,1),(31,3,8,1,2),(32,3,9,2,1),(33,4,2,8,1),(34,4,3,8,1),(35,4,4,8,1),(36,4,5,6,1),(37,4,5,4,2),(38,4,6,6,1),(39,4,6,4,2),(40,4,7,6,1),(41,4,7,4,2),(42,4,8,1,1),(43,4,9,2,1),(44,5,2,8,1),(45,5,2,9,2),(46,5,3,8,1),(47,5,3,9,2),(48,5,4,8,1),(49,5,4,9,2),(50,5,5,4,1),(51,5,6,4,1),(52,5,7,4,1),(53,5,8,4,1),(54,5,8,1,2),(55,5,9,2,1),(56,6,2,9,1),(57,6,3,9,1),(58,6,4,9,1),(59,6,5,4,1),(60,6,6,4,1),(61,6,7,4,1),(62,6,7,3,2),(63,6,8,3,1),(64,6,8,4,2),(65,6,8,1,3),(66,6,9,2,1),(67,7,2,9,1),(68,7,3,9,1),(69,7,4,9,1),(70,7,5,3,1),(71,7,6,3,1),(72,7,7,3,1),(73,7,8,3,1),(74,7,8,1,2),(75,7,9,2,1);
/*!40000 ALTER TABLE `defensive_alignment` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:17:56
