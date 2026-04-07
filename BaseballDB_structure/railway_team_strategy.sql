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
-- Table structure for table `team_strategy`
--

DROP TABLE IF EXISTS `team_strategy`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `team_strategy` (
  `id` int NOT NULL AUTO_INCREMENT,
  `team_id` int NOT NULL,
  `outfield_spacing` enum('normal','deep','shallow','shift_pull','shift_oppo') NOT NULL DEFAULT 'normal',
  `infield_spacing` enum('normal','in','double_play','shift_pull','shift_oppo') NOT NULL DEFAULT 'normal',
  `bullpen_cutoff` int NOT NULL DEFAULT '100' COMMENT 'pitch count at which SP is considered for pull',
  `bullpen_priority` enum('rest','matchup','best_available') NOT NULL DEFAULT 'rest',
  `emergency_pitcher_id` int DEFAULT NULL COMMENT 'player_id of emergency position-player pitcher',
  `intentional_walk_list` json DEFAULT NULL COMMENT 'array of opposing player_ids to IBB',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_team_strategy` (`team_id`),
  KEY `fk_ts_emergency` (`emergency_pitcher_id`),
  CONSTRAINT `fk_ts_emergency` FOREIGN KEY (`emergency_pitcher_id`) REFERENCES `simbbPlayers` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_ts_team` FOREIGN KEY (`team_id`) REFERENCES `teams` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=32 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `team_strategy`
--

LOCK TABLES `team_strategy` WRITE;
/*!40000 ALTER TABLE `team_strategy` DISABLE KEYS */;
INSERT INTO `team_strategy` VALUES (1,1,'normal','normal',100,'rest',54635,NULL,'2026-03-14 08:05:11','2026-03-14 08:05:11'),(2,2,'normal','normal',100,'rest',64367,NULL,'2026-03-14 08:05:13','2026-03-14 08:05:13'),(3,3,'normal','normal',100,'rest',53656,NULL,'2026-03-14 08:05:15','2026-03-14 08:05:15'),(4,4,'normal','normal',100,'rest',68025,NULL,'2026-03-14 08:05:17','2026-03-14 08:05:17'),(5,5,'normal','normal',100,'rest',42807,NULL,'2026-03-14 08:05:19','2026-03-14 08:05:19'),(6,6,'normal','normal',100,'rest',65463,NULL,'2026-03-14 08:05:21','2026-03-14 08:05:21'),(7,7,'normal','normal',100,'rest',44904,NULL,'2026-03-14 08:05:22','2026-03-14 08:05:22'),(8,8,'normal','normal',100,'rest',66737,NULL,'2026-03-14 08:05:24','2026-03-14 08:05:24'),(9,9,'normal','normal',95,'rest',54471,'[]','2026-03-14 08:05:26','2026-03-16 20:27:06'),(10,10,'normal','normal',100,'rest',51523,NULL,'2026-03-14 08:05:28','2026-03-14 08:05:28'),(11,11,'normal','normal',100,'rest',58836,NULL,'2026-03-14 08:05:30','2026-03-14 08:05:30'),(12,12,'normal','normal',100,'rest',52498,NULL,'2026-03-14 08:05:31','2026-03-14 08:05:31'),(13,13,'normal','normal',100,'rest',39683,NULL,'2026-03-14 08:05:33','2026-03-14 08:05:33'),(14,14,'normal','normal',100,'rest',55372,NULL,'2026-03-14 08:05:35','2026-03-14 08:05:35'),(15,15,'normal','normal',100,'rest',42878,NULL,'2026-03-14 08:05:37','2026-03-14 08:05:37'),(16,16,'normal','normal',100,'rest',60360,NULL,'2026-03-14 08:05:39','2026-03-14 08:05:39'),(17,17,'normal','normal',100,'rest',50121,NULL,'2026-03-14 08:05:41','2026-03-14 08:05:41'),(18,18,'normal','normal',100,'rest',53249,NULL,'2026-03-14 08:05:42','2026-03-14 08:05:42'),(19,19,'normal','normal',100,'rest',59924,NULL,'2026-03-14 08:05:44','2026-03-14 08:05:44'),(20,20,'normal','normal',100,'rest',48232,NULL,'2026-03-14 08:05:46','2026-03-14 08:05:46'),(21,21,'normal','normal',100,'rest',46397,NULL,'2026-03-14 08:05:48','2026-03-14 08:05:48'),(22,22,'normal','normal',100,'rest',56041,NULL,'2026-03-14 08:05:50','2026-03-14 08:05:50'),(23,23,'normal','normal',100,'rest',50451,NULL,'2026-03-14 08:05:51','2026-03-14 08:05:51'),(24,24,'normal','normal',100,'rest',64557,NULL,'2026-03-14 08:05:53','2026-03-14 08:05:53'),(25,25,'normal','normal',100,'rest',46188,NULL,'2026-03-14 08:05:55','2026-03-14 08:05:55'),(26,26,'normal','normal',100,'rest',56614,NULL,'2026-03-14 08:05:57','2026-03-14 08:05:57'),(27,27,'normal','normal',100,'rest',43087,NULL,'2026-03-14 08:05:59','2026-03-14 08:05:59'),(28,28,'normal','normal',100,'rest',62998,NULL,'2026-03-14 08:06:00','2026-03-14 08:06:00'),(29,29,'normal','normal',100,'rest',53954,NULL,'2026-03-14 08:06:02','2026-03-14 08:06:02'),(30,30,'normal','normal',100,'rest',52962,NULL,'2026-03-14 08:06:04','2026-03-14 08:06:04');
/*!40000 ALTER TABLE `team_strategy` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:14:34
