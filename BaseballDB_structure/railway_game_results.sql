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
-- Table structure for table `game_results`
--

DROP TABLE IF EXISTS `game_results`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `game_results` (
  `game_id` int NOT NULL,
  `season` int NOT NULL,
  `league_level` int NOT NULL,
  `season_week` int NOT NULL,
  `season_subweek` char(1) NOT NULL,
  `home_team_id` int NOT NULL,
  `away_team_id` int NOT NULL,
  `home_score` int NOT NULL,
  `away_score` int NOT NULL,
  `winning_team_id` int DEFAULT NULL,
  `losing_team_id` int DEFAULT NULL,
  `winning_org_id` int DEFAULT NULL,
  `losing_org_id` int DEFAULT NULL,
  `game_outcome` enum('HOME_WIN','AWAY_WIN','TIE','CANCELLED') NOT NULL,
  `boxscore_json` json DEFAULT NULL,
  `play_by_play_json` longtext,
  `completed_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `game_type` varchar(20) NOT NULL DEFAULT 'regular',
  PRIMARY KEY (`game_id`),
  KEY `fk_game_results_team_home` (`home_team_id`),
  KEY `fk_game_results_team_away` (`away_team_id`),
  KEY `idx_game_results_season_level_week` (`season`,`league_level`,`season_week`),
  KEY `idx_game_results_winning_org` (`winning_org_id`),
  KEY `idx_game_results_losing_org` (`losing_org_id`),
  KEY `idx_game_results_game_type` (`game_type`),
  CONSTRAINT `fk_game_results_gamelist` FOREIGN KEY (`game_id`) REFERENCES `gamelist` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_game_results_org_lose` FOREIGN KEY (`losing_org_id`) REFERENCES `organizations` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_game_results_org_win` FOREIGN KEY (`winning_org_id`) REFERENCES `organizations` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_game_results_team_away` FOREIGN KEY (`away_team_id`) REFERENCES `teams` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_game_results_team_home` FOREIGN KEY (`home_team_id`) REFERENCES `teams` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `game_results`
--

LOCK TABLES `game_results` WRITE;
/*!40000 ALTER TABLE `game_results` DISABLE KEYS */;
/*!40000 ALTER TABLE `game_results` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:08:53
