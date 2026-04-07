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
-- Table structure for table `org_ledger_entries`
--

DROP TABLE IF EXISTS `org_ledger_entries`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `org_ledger_entries` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `org_id` int NOT NULL,
  `league_year_id` int NOT NULL,
  `game_week_id` int DEFAULT NULL,
  `entry_type` varchar(32) NOT NULL,
  `amount` decimal(18,2) NOT NULL,
  `contract_id` int DEFAULT NULL,
  `player_id` int DEFAULT NULL,
  `note` varchar(255) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_ledger_league_years` (`league_year_id`),
  KEY `fk_ledger_game_weeks` (`game_week_id`),
  KEY `idx_ledger_org_year_week` (`org_id`,`league_year_id`,`game_week_id`),
  KEY `idx_ledger_org_type` (`org_id`,`entry_type`),
  KEY `idx_ledger_contract` (`contract_id`),
  KEY `idx_ledger_player` (`player_id`),
  CONSTRAINT `fk_ledger_contracts` FOREIGN KEY (`contract_id`) REFERENCES `contracts` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_ledger_orgs` FOREIGN KEY (`org_id`) REFERENCES `organizations` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ledger_players` FOREIGN KEY (`player_id`) REFERENCES `simbbPlayers` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=41302534 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `org_ledger_entries`
--

LOCK TABLES `org_ledger_entries` WRITE;
/*!40000 ALTER TABLE `org_ledger_entries` DISABLE KEYS */;
INSERT INTO `org_ledger_entries` VALUES (41302504,1,1,NULL,'media',191880000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:32'),(41302505,2,1,NULL,'media',81180000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:32'),(41302506,3,1,NULL,'media',59040000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:32'),(41302507,4,1,NULL,'media',73800000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:32'),(41302508,5,1,NULL,'media',191880000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:32'),(41302509,6,1,NULL,'media',56580000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:32'),(41302510,7,1,NULL,'media',46740000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302511,8,1,NULL,'media',93480000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302512,9,1,NULL,'media',61500000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302513,10,1,NULL,'media',41820000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302514,11,1,NULL,'media',59040000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302515,12,1,NULL,'media',145140000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302516,13,1,NULL,'media',78720000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302517,14,1,NULL,'media',91020000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302518,15,1,NULL,'media',59040000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302519,16,1,NULL,'media',98400000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302520,17,1,NULL,'media',91020000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:33'),(41302521,18,1,NULL,'media',44280000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302522,19,1,NULL,'media',63960000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302523,20,1,NULL,'media',83640000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302524,21,1,NULL,'media',51660000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302525,22,1,NULL,'media',98400000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302526,23,1,NULL,'media',88560000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302527,24,1,NULL,'media',46740000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302528,25,1,NULL,'media',71340000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302529,26,1,NULL,'media',54120000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302530,27,1,NULL,'media',145140000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:34'),(41302531,28,1,NULL,'media',66420000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:35'),(41302532,29,1,NULL,'media',41820000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:35'),(41302533,30,1,NULL,'media',88560000.00,NULL,NULL,'Media payout for league_year 2026','2026-03-24 23:39:35');
/*!40000 ALTER TABLE `org_ledger_entries` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:09:44
