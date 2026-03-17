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
SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-03-17 10:16:06
