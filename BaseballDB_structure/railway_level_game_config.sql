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
-- Table structure for table `level_game_config`
--

DROP TABLE IF EXISTS `level_game_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `level_game_config` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `league_level` int unsigned NOT NULL,
  `error_rate` float NOT NULL DEFAULT '0.05',
  `steal_success` float NOT NULL DEFAULT '0.65',
  `pickoff_success` float NOT NULL DEFAULT '0.1',
  `pregame_injury_base_rate` float NOT NULL DEFAULT '0.1',
  `ingame_injury_base_rate` float NOT NULL DEFAULT '0.1',
  `energy_tick_cap` float NOT NULL DEFAULT '1.5',
  `energy_step` float NOT NULL DEFAULT '2',
  `short_leash` float NOT NULL DEFAULT '0.8',
  `normal_leash` float NOT NULL DEFAULT '0.7',
  `long_leash` float NOT NULL DEFAULT '0.5',
  `fielding_multiplier` float NOT NULL DEFAULT '0',
  `stamina_recovery_per_subweek` decimal(5,2) NOT NULL DEFAULT '5.00',
  `durability_mult_iron_man` decimal(4,2) NOT NULL DEFAULT '1.50',
  `durability_mult_dependable` decimal(4,2) NOT NULL DEFAULT '1.25',
  `durability_mult_normal` decimal(4,2) NOT NULL DEFAULT '1.00',
  `durability_mult_undependable` decimal(4,2) NOT NULL DEFAULT '0.75',
  `durability_mult_tires_easily` decimal(4,2) NOT NULL DEFAULT '0.50',
  `stamina_recovery_pitcher_per_subweek` decimal(5,2) NOT NULL DEFAULT '5.00',
  PRIMARY KEY (`id`),
  UNIQUE KEY `league_level` (`league_level`),
  KEY `idx_level` (`league_level`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `level_game_config`
--

LOCK TABLES `level_game_config` WRITE;
/*!40000 ALTER TABLE `level_game_config` DISABLE KEYS */;
INSERT INTO `level_game_config` VALUES (1,9,0.02,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50),(2,8,0.022,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50),(3,7,0.025,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50),(4,6,0.028,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50),(5,5,0.031,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50),(6,4,0.034,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50),(7,3,0.037,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50),(8,2,0.04,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50),(9,1,0.05,0.65,0.1,0.0005,0.001,1.5,2,0.8,0.7,0.5,0,5.00,1.50,1.25,1.00,0.75,0.50,8.50);
/*!40000 ALTER TABLE `level_game_config` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:13:36
