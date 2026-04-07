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
-- Table structure for table `scouting_config`
--

DROP TABLE IF EXISTS `scouting_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `scouting_config` (
  `id` int NOT NULL AUTO_INCREMENT,
  `config_key` varchar(64) NOT NULL,
  `config_value` varchar(255) NOT NULL,
  `description` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_config_key` (`config_key`)
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `scouting_config`
--

LOCK TABLES `scouting_config` WRITE;
/*!40000 ALTER TABLE `scouting_config` DISABLE KEYS */;
INSERT INTO `scouting_config` VALUES (1,'mlb_budget_per_year','1000','Scouting points per MLB org per league year'),(2,'college_budget_per_year','500','Scouting points per college org per league year'),(3,'hs_report_cost','10','Cost: HS text scouting report'),(4,'hs_potential_cost_legacy','25','DEPRECATED: replaced by recruit_potential_fuzzed_cost + recruit_potential_precise_cost'),(5,'pro_numeric_cost_legacy','15','DEPRECATED: replaced by draft_attrs_fuzzed_cost + draft_attrs_precise_cost'),(6,'recruit_potential_fuzzed_cost','15','Cost: fuzzed potential for HS recruit'),(7,'recruit_potential_precise_cost','25','Cost: precise potential for HS recruit'),(8,'college_potential_precise_cost','15','Cost: precise potential for college player'),(9,'draft_attrs_fuzzed_cost','10','Cost: fuzzed 20-80 for draft-eligible player'),(10,'draft_attrs_precise_cost','20','Cost: precise 20-80 for draft-eligible player'),(11,'draft_potential_precise_cost','15','Cost: precise potential for draft-eligible player'),(12,'pro_attrs_precise_cost','15','Cost: precise 20-80 for pro roster player'),(13,'pro_potential_precise_cost','15','Cost: precise potential for pro roster player');
/*!40000 ALTER TABLE `scouting_config` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:17:03
