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
-- Table structure for table `level_contact_odds`
--

DROP TABLE IF EXISTS `level_contact_odds`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `level_contact_odds` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `league_level` int unsigned NOT NULL,
  `contact_type_id` int unsigned NOT NULL,
  `odds` float NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_level_contact` (`league_level`,`contact_type_id`),
  KEY `idx_level` (`league_level`),
  KEY `contact_type_id` (`contact_type_id`),
  KEY `idx_level_contact_odds_full` (`league_level`,`contact_type_id`),
  CONSTRAINT `level_contact_odds_ibfk_1` FOREIGN KEY (`contact_type_id`) REFERENCES `contact_types` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=64 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `level_contact_odds`
--

LOCK TABLES `level_contact_odds` WRITE;
/*!40000 ALTER TABLE `level_contact_odds` DISABLE KEYS */;
INSERT INTO `level_contact_odds` VALUES (1,9,1,7),(2,9,2,11),(3,9,3,12),(4,9,4,16),(5,9,5,20),(6,9,6,30),(7,9,7,4),(8,8,1,7),(9,8,2,11),(10,8,3,12),(11,8,4,16),(12,8,5,20),(13,8,6,30),(14,8,7,4),(15,7,1,7),(16,7,2,11),(17,7,3,12),(18,7,4,16),(19,7,5,20),(20,7,6,30),(21,7,7,4),(22,6,1,7),(23,6,2,11),(24,6,3,12),(25,6,4,16),(26,6,5,20),(27,6,6,30),(28,6,7,4),(29,5,1,7),(30,5,2,11),(31,5,3,12),(32,5,4,16),(33,5,5,20),(34,5,6,30),(35,5,7,4),(36,4,1,7),(37,4,2,11),(38,4,3,12),(39,4,4,16),(40,4,5,20),(41,4,6,30),(42,4,7,4),(43,3,1,7),(44,3,2,11),(45,3,3,12),(46,3,4,16),(47,3,5,20),(48,3,6,30),(49,3,7,4),(50,2,1,7),(51,2,2,11),(52,2,3,12),(53,2,4,16),(54,2,5,20),(55,2,6,30),(56,2,7,4),(57,1,1,7),(58,1,2,11),(59,1,3,12),(60,1,4,16),(61,1,5,20),(62,1,6,30),(63,1,7,4);
/*!40000 ALTER TABLE `level_contact_odds` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:18:59
