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
-- Table structure for table `college_baseball_requests`
--

DROP TABLE IF EXISTS `college_baseball_requests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `college_baseball_requests` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `username` varchar(255) NOT NULL,
  `org_id` int NOT NULL,
  `is_approved` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_college_requests_org` (`org_id`),
  CONSTRAINT `fk_college_requests_org` FOREIGN KEY (`org_id`) REFERENCES `organizations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=27 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `college_baseball_requests`
--

LOCK TABLES `college_baseball_requests` WRITE;
/*!40000 ALTER TABLE `college_baseball_requests` DISABLE KEYS */;
INSERT INTO `college_baseball_requests` VALUES (1,'alexfall862',206,1,'2026-03-01 04:36:34','2026-03-01 04:36:54'),(2,'alexfall862',206,1,'2026-03-14 17:06:19','2026-03-14 17:06:33'),(3,'TuscanSota',341,1,'2026-03-14 18:27:46','2026-03-14 20:48:57'),(4,'Fireballer34',154,1,'2026-03-14 18:49:41','2026-03-14 20:49:04'),(5,'smackemz3',337,0,'2026-03-14 19:43:58','2026-03-14 19:43:58'),(6,'LordLittlebutt',141,0,'2026-03-14 20:09:51','2026-03-14 20:09:51'),(7,'Ricky Campbell',90,0,'2026-03-14 20:38:23','2026-03-14 20:38:23'),(8,'kgreene829',142,0,'2026-03-14 20:40:42','2026-03-14 20:40:42'),(9,'Newkbomb',338,0,'2026-03-14 20:45:28','2026-03-14 20:45:28'),(10,'jmjacobs',49,0,'2026-03-14 20:48:31','2026-03-14 20:48:31'),(11,'nemolee.exe',111,0,'2026-03-14 21:11:53','2026-03-14 21:11:53'),(12,'Dr_Novella',69,0,'2026-03-14 21:35:39','2026-03-14 21:35:39'),(13,'cbreezy',34,0,'2026-03-14 21:43:32','2026-03-14 21:43:32'),(14,'failedchompers',187,0,'2026-03-14 21:44:59','2026-03-14 21:44:59'),(15,'Bellwood',316,0,'2026-03-14 22:18:07','2026-03-14 22:18:07'),(16,'Spoof',275,1,'2026-03-14 22:48:50','2026-03-16 00:44:01'),(17,'Mightydog135',188,0,'2026-03-14 23:57:35','2026-03-14 23:57:35'),(18,'PoopyRhinoPickle',250,0,'2026-03-15 14:15:28','2026-03-15 14:15:28'),(19,'bundy',336,1,'2026-03-15 21:15:04','2026-03-15 21:21:11'),(20,'tsweezy',284,1,'2026-03-16 00:43:12','2026-03-16 00:43:57'),(21,'Ezaco',134,1,'2026-03-17 17:29:32','2026-03-17 17:30:17'),(22,'Sarge',103,0,'2026-03-18 06:05:01','2026-03-18 06:05:01'),(23,'dotNectar',82,0,'2026-03-19 19:07:02','2026-03-19 19:07:02'),(24,'Angus',169,0,'2026-03-21 12:38:16','2026-03-21 12:38:16'),(25,'Matty460',298,0,'2026-03-21 15:24:07','2026-03-21 15:24:07'),(26,'chaserck',62,0,'2026-03-27 02:42:34','2026-03-27 02:42:34');
/*!40000 ALTER TABLE `college_baseball_requests` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:12:36
