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
-- Table structure for table `gamelist`
--

DROP TABLE IF EXISTS `gamelist`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `gamelist` (
  `id` int NOT NULL AUTO_INCREMENT,
  `away_team` int NOT NULL,
  `home_team` int NOT NULL,
  `season_week` int NOT NULL,
  `season_subweek` varchar(2) DEFAULT NULL,
  `league_level` int NOT NULL,
  `season` int NOT NULL DEFAULT '1',
  `random_seed` bigint DEFAULT NULL,
  `game_type` varchar(20) NOT NULL DEFAULT 'regular',
  PRIMARY KEY (`id`),
  KEY `away_team` (`away_team`),
  KEY `home_team` (`home_team`),
  KEY `idx_gamelist_week` (`season`,`season_week`,`season_subweek`),
  KEY `idx_gamelist_level` (`league_level`,`season_week`),
  KEY `idx_gamelist_game_type` (`game_type`),
  CONSTRAINT `fk_game_seasons` FOREIGN KEY (`season`) REFERENCES `seasons` (`id`),
  CONSTRAINT `gamelist_ibfk_1` FOREIGN KEY (`away_team`) REFERENCES `teams` (`id`),
  CONSTRAINT `gamelist_ibfk_2` FOREIGN KEY (`home_team`) REFERENCES `teams` (`id`),
  CONSTRAINT `gamelist_ibfk_3` FOREIGN KEY (`league_level`) REFERENCES `levels` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=58173 DEFAULT CHARSET=utf8mb3;
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

-- Dump completed on 2026-03-17 10:17:58
