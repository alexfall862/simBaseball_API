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
-- Table structure for table `mlb_requests`
--

DROP TABLE IF EXISTS `mlb_requests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `mlb_requests` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `username` varchar(255) NOT NULL,
  `org_id` int NOT NULL,
  `role` varchar(10) NOT NULL COMMENT '"o", "gm", "mgr", or "sc"',
  `is_owner` tinyint(1) NOT NULL DEFAULT '0',
  `is_gm` tinyint(1) NOT NULL DEFAULT '0',
  `is_manager` tinyint(1) NOT NULL DEFAULT '0',
  `is_scout` tinyint(1) NOT NULL DEFAULT '0',
  `is_approved` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_mlb_requests_org` (`org_id`),
  CONSTRAINT `fk_mlb_requests_org` FOREIGN KEY (`org_id`) REFERENCES `organizations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `mlb_requests`
--

LOCK TABLES `mlb_requests` WRITE;
/*!40000 ALTER TABLE `mlb_requests` DISABLE KEYS */;
INSERT INTO `mlb_requests` VALUES (2,'alexfall862',4,'o',1,0,0,0,1,'2026-02-28 20:12:05','2026-02-28 20:12:18'),(3,'TuscanSota',25,'mgr',0,0,1,0,1,'2026-03-14 17:26:29','2026-03-14 20:48:15'),(4,'Ezaco',29,'o',1,0,0,0,1,'2026-03-14 17:34:04','2026-03-14 20:48:08'),(5,'Fireballer34',1,'o',1,0,0,0,1,'2026-03-14 18:14:14','2026-03-14 20:48:11'),(6,'Bellwood',15,'o',1,0,0,0,0,'2026-03-14 19:44:16','2026-03-14 19:44:16'),(7,'LordLittlebutt',16,'o',1,0,0,0,0,'2026-03-14 20:11:46','2026-03-14 20:11:46'),(8,'kgreene829',6,'o',1,0,0,0,0,'2026-03-14 20:40:17','2026-03-14 20:40:17'),(9,'Rocketcan',23,'o',1,0,0,0,1,'2026-03-14 20:42:25','2026-03-18 03:46:56'),(10,'jmjacobs',1,'o',1,0,0,0,0,'2026-03-14 20:46:33','2026-03-14 20:46:33'),(11,'Jieret',25,'o',1,0,0,0,0,'2026-03-14 20:50:50','2026-03-14 20:50:50'),(12,'bundy',19,'o',1,0,0,0,1,'2026-03-14 20:56:26','2026-03-15 21:18:06'),(13,'anonemuss',2,'o',1,0,0,0,0,'2026-03-14 21:02:49','2026-03-14 21:02:49'),(14,'nemolee.exe',22,'o',1,0,0,0,0,'2026-03-14 21:13:04','2026-03-14 21:13:04'),(15,'Dr_Novella',14,'o',1,0,0,0,0,'2026-03-14 21:35:55','2026-03-14 21:35:55'),(16,'Spoof',18,'mgr',0,0,1,0,1,'2026-03-14 21:52:50','2026-03-14 21:53:53'),(17,'Minnow',19,'gm',0,1,0,0,0,'2026-03-14 22:17:25','2026-03-14 22:17:25'),(18,'Dearden',27,'o',1,0,0,0,0,'2026-03-14 22:19:48','2026-03-14 22:19:48'),(19,'Newkbomb',10,'o',1,0,0,0,0,'2026-03-14 22:54:46','2026-03-14 22:54:46'),(20,'tsweezy',9,'o',1,0,0,0,1,'2026-03-16 00:43:00','2026-03-16 00:43:49'),(21,'Matty460',11,'o',1,0,0,0,0,'2026-03-21 15:21:56','2026-03-21 15:21:56'),(22,'Jitters',3,'o',1,0,0,0,0,'2026-03-21 15:22:11','2026-03-21 15:22:11'),(23,'SandyToez',30,'o',1,0,0,0,0,'2026-03-21 20:29:50','2026-03-21 20:29:50'),(24,'chaserck',14,'o',1,0,0,0,0,'2026-03-27 02:40:10','2026-03-27 02:40:10');
/*!40000 ALTER TABLE `mlb_requests` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:05:32
