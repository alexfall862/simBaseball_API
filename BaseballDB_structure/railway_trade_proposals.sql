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
-- Table structure for table `trade_proposals`
--

DROP TABLE IF EXISTS `trade_proposals`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `trade_proposals` (
  `id` int NOT NULL AUTO_INCREMENT,
  `proposing_org_id` int NOT NULL,
  `receiving_org_id` int NOT NULL,
  `league_year_id` int NOT NULL,
  `status` enum('proposed','counterparty_accepted','counterparty_rejected','admin_approved','admin_rejected','executed','cancelled','expired') NOT NULL DEFAULT 'proposed',
  `proposal` json NOT NULL,
  `proposed_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `counterparty_acted_at` datetime DEFAULT NULL,
  `admin_acted_at` datetime DEFAULT NULL,
  `executed_at` datetime DEFAULT NULL,
  `counterparty_note` varchar(500) DEFAULT NULL,
  `admin_note` varchar(500) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tp_status` (`status`),
  KEY `idx_tp_orgs` (`proposing_org_id`,`receiving_org_id`),
  KEY `idx_tp_receiving` (`receiving_org_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `trade_proposals`
--

LOCK TABLES `trade_proposals` WRITE;
/*!40000 ALTER TABLE `trade_proposals` DISABLE KEYS */;
/*!40000 ALTER TABLE `trade_proposals` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:16:32
