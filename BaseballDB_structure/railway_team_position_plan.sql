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
-- Table structure for table `team_position_plan`
--

DROP TABLE IF EXISTS `team_position_plan`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `team_position_plan` (
  `id` int NOT NULL AUTO_INCREMENT,
  `team_id` int NOT NULL,
  `position_code` enum('c','fb','sb','tb','ss','lf','cf','rf','dh','p') NOT NULL,
  `vs_hand` enum('L','R','both') NOT NULL DEFAULT 'both',
  `player_id` int NOT NULL,
  `target_weight` decimal(6,4) NOT NULL DEFAULT '1.0000',
  `priority` int NOT NULL DEFAULT '1',
  `locked` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `lineup_role` varchar(20) NOT NULL DEFAULT 'balanced',
  `min_order` smallint DEFAULT NULL,
  `max_order` smallint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tpp_team_pos_hand` (`team_id`,`position_code`,`vs_hand`),
  KEY `idx_tpp_team_player` (`team_id`,`player_id`),
  KEY `fk_tpp_player` (`player_id`),
  KEY `idx_position_plan_team_lookup` (`team_id`,`position_code`,`vs_hand`,`priority`),
  CONSTRAINT `fk_tpp_player` FOREIGN KEY (`player_id`) REFERENCES `simbbPlayers` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_tpp_team` FOREIGN KEY (`team_id`) REFERENCES `teams` (`id`) ON DELETE CASCADE,
  CONSTRAINT `chk_lineup_role` CHECK ((`lineup_role` in (_utf8mb4'table_setter',_utf8mb4'on_base',_utf8mb4'slugger',_utf8mb4'balanced',_utf8mb4'speed',_utf8mb4'bottom'))),
  CONSTRAINT `chk_max_order` CHECK (((`max_order` is null) or ((`max_order` >= 1) and (`max_order` <= 9)))),
  CONSTRAINT `chk_min_order` CHECK (((`min_order` is null) or ((`min_order` >= 1) and (`min_order` <= 9)))),
  CONSTRAINT `chk_order_range` CHECK (((`min_order` is null) or (`max_order` is null) or (`min_order` <= `max_order`)))
) ENGINE=InnoDB AUTO_INCREMENT=658 DEFAULT CHARSET=utf8mb3;
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

-- Dump completed on 2026-03-17 10:17:27
