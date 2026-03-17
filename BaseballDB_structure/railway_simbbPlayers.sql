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
-- Table structure for table `simbbPlayers`
--

DROP TABLE IF EXISTS `simbbPlayers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `simbbPlayers` (
  `id` int NOT NULL,
  `age` int DEFAULT NULL,
  `area` varchar(255) DEFAULT NULL,
  `arm_angle` varchar(255) DEFAULT NULL,
  `basereaction_base` float DEFAULT NULL,
  `basereaction_pot` varchar(255) DEFAULT NULL,
  `baserunning_base` float DEFAULT NULL,
  `baserunning_pot` varchar(255) DEFAULT NULL,
  `catchframe_base` float DEFAULT NULL,
  `catchframe_pot` varchar(255) DEFAULT NULL,
  `catchsequence_base` float DEFAULT NULL,
  `catchsequence_pot` varchar(255) DEFAULT NULL,
  `city` varchar(255) DEFAULT NULL,
  `contact_base` float DEFAULT NULL,
  `contact_pot` varchar(255) DEFAULT NULL,
  `discipline_base` float DEFAULT NULL,
  `discipline_pot` varchar(255) DEFAULT NULL,
  `durability` varchar(255) DEFAULT NULL,
  `eye_base` float DEFAULT NULL,
  `eye_pot` varchar(255) DEFAULT NULL,
  `fieldcatch_base` float DEFAULT NULL,
  `fieldcatch_pot` varchar(255) DEFAULT NULL,
  `fieldreact_base` float DEFAULT NULL,
  `fieldreact_pot` varchar(255) DEFAULT NULL,
  `fieldspot_base` float DEFAULT NULL,
  `fieldspot_pot` varchar(255) DEFAULT NULL,
  `firstname` varchar(255) DEFAULT NULL,
  `lastname` varchar(255) DEFAULT NULL,
  `bat_hand` varchar(255) DEFAULT NULL,
  `pitch_hand` varchar(255) DEFAULT NULL,
  `height` int DEFAULT NULL,
  `injury_risk` varchar(255) DEFAULT NULL,
  `intorusa` varchar(255) DEFAULT NULL,
  `pendurance_base` float DEFAULT NULL,
  `pendurance_pot` varchar(255) DEFAULT NULL,
  `pgencontrol_base` float DEFAULT NULL,
  `pgencontrol_pot` varchar(255) DEFAULT NULL,
  `pickoff_base` float DEFAULT NULL,
  `pickoff_pot` varchar(255) DEFAULT NULL,
  `pitch1_name` varchar(255) DEFAULT NULL,
  `pitch1_consist_base` float DEFAULT NULL,
  `pitch1_consist_pot` varchar(255) DEFAULT NULL,
  `pitch1_pacc_base` float DEFAULT NULL,
  `pitch1_pacc_pot` varchar(255) DEFAULT NULL,
  `pitch1_pbrk_base` float DEFAULT NULL,
  `pitch1_pbrk_pot` varchar(255) DEFAULT NULL,
  `pitch1_pcntrl_base` float DEFAULT NULL,
  `pitch1_pcntrl_pot` varchar(255) DEFAULT NULL,
  `pitch1_ovr` float DEFAULT NULL,
  `pitch2_name` varchar(255) DEFAULT NULL,
  `pitch2_consist_base` float DEFAULT NULL,
  `pitch2_consist_pot` varchar(255) DEFAULT NULL,
  `pitch2_pacc_base` float DEFAULT NULL,
  `pitch2_pacc_pot` varchar(255) DEFAULT NULL,
  `pitch2_pbrk_base` float DEFAULT NULL,
  `pitch2_pbrk_pot` varchar(255) DEFAULT NULL,
  `pitch2_pcntrl_base` float DEFAULT NULL,
  `pitch2_pcntrl_pot` varchar(255) DEFAULT NULL,
  `pitch2_ovr` float DEFAULT NULL,
  `pitch3_name` varchar(255) DEFAULT NULL,
  `pitch3_consist_base` float DEFAULT NULL,
  `pitch3_consist_pot` varchar(255) DEFAULT NULL,
  `pitch3_pacc_base` float DEFAULT NULL,
  `pitch3_pacc_pot` varchar(255) DEFAULT NULL,
  `pitch3_pbrk_base` float DEFAULT NULL,
  `pitch3_pbrk_pot` varchar(255) DEFAULT NULL,
  `pitch3_pcntrl_base` float DEFAULT NULL,
  `pitch3_pcntrl_pot` varchar(255) DEFAULT NULL,
  `pitch3_ovr` float DEFAULT NULL,
  `pitch4_name` varchar(255) DEFAULT NULL,
  `pitch4_consist_base` float DEFAULT NULL,
  `pitch4_consist_pot` varchar(255) DEFAULT NULL,
  `pitch4_pacc_base` float DEFAULT NULL,
  `pitch4_pacc_pot` varchar(255) DEFAULT NULL,
  `pitch4_pbrk_base` float DEFAULT NULL,
  `pitch4_pbrk_pot` varchar(255) DEFAULT NULL,
  `pitch4_pcntrl_base` float DEFAULT NULL,
  `pitch4_pcntrl_pot` varchar(255) DEFAULT NULL,
  `pitch4_ovr` float DEFAULT NULL,
  `pitch5_name` varchar(255) DEFAULT NULL,
  `pitch5_consist_base` float DEFAULT NULL,
  `pitch5_consist_pot` varchar(255) DEFAULT NULL,
  `pitch5_pacc_base` float DEFAULT NULL,
  `pitch5_pacc_pot` varchar(255) DEFAULT NULL,
  `pitch5_pbrk_base` float DEFAULT NULL,
  `pitch5_pbrk_pot` varchar(255) DEFAULT NULL,
  `pitch5_pcntrl_base` float DEFAULT NULL,
  `pitch5_pcntrl_pot` varchar(255) DEFAULT NULL,
  `pitch5_ovr` float DEFAULT NULL,
  `power_base` float DEFAULT NULL,
  `power_pot` varchar(255) DEFAULT NULL,
  `psequencing_base` float DEFAULT NULL,
  `psequencing_pot` varchar(255) DEFAULT NULL,
  `pthrowpower_base` float DEFAULT NULL,
  `pthrowpower_pot` varchar(255) DEFAULT NULL,
  `ptype` varchar(255) DEFAULT NULL,
  `speed_base` float DEFAULT NULL,
  `speed_pot` varchar(255) DEFAULT NULL,
  `left_split` float DEFAULT NULL,
  `center_split` float DEFAULT NULL,
  `right_split` float DEFAULT NULL,
  `throwacc_base` float DEFAULT NULL,
  `throwacc_pot` varchar(255) DEFAULT NULL,
  `throwpower_base` float DEFAULT NULL,
  `throwpower_pot` varchar(255) DEFAULT NULL,
  `weight` int DEFAULT NULL,
  `displayovr` varchar(4) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
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

-- Dump completed on 2026-03-17 10:16:08
