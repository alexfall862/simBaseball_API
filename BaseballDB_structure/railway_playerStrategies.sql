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
-- Table structure for table `playerStrategies`
--

DROP TABLE IF EXISTS `playerStrategies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `playerStrategies` (
  `id` int NOT NULL AUTO_INCREMENT,
  `playerID` int NOT NULL,
  `orgID` int NOT NULL,
  `userID` int DEFAULT NULL,
  `plate_approach` varchar(64) DEFAULT NULL,
  `pitching_approach` varchar(64) DEFAULT NULL,
  `baserunning_approach` varchar(64) DEFAULT NULL,
  `usage_preference` varchar(32) DEFAULT NULL,
  `stealfreq` decimal(5,2) DEFAULT NULL,
  `pickofffreq` decimal(5,2) DEFAULT NULL,
  `pitchchoices` json DEFAULT NULL,
  `pitchpull` int DEFAULT NULL COMMENT 'pitch count to consider pulling; NULL = use team default',
  `pulltend` enum('normal','quick','long') DEFAULT NULL COMMENT 'leash tendency; NULL = normal',
  PRIMARY KEY (`id`),
  KEY `fk_player_strategy_idx` (`playerID`),
  KEY `fk_org_strategy_idx` (`orgID`),
  KEY `fk_user_strategy_idx` (`userID`),
  KEY `idx_strategies_player` (`playerID`,`orgID`),
  CONSTRAINT `fk_org_strategy` FOREIGN KEY (`orgID`) REFERENCES `organizations` (`id`),
  CONSTRAINT `fk_player_strategy` FOREIGN KEY (`playerID`) REFERENCES `simbbPlayers` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=52 DEFAULT CHARSET=utf8mb3;
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

-- Dump completed on 2026-03-17 10:17:22
