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
-- Table structure for table `organizations`
--

DROP TABLE IF EXISTS `organizations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `organizations` (
  `org_abbrev` varchar(45) DEFAULT NULL,
  `cash` decimal(15,2) DEFAULT NULL,
  `mlb` int DEFAULT NULL,
  `aaa` int DEFAULT NULL,
  `aa` int DEFAULT NULL,
  `a` int DEFAULT NULL,
  `higha` int DEFAULT NULL,
  `scraps` int DEFAULT NULL,
  `id` int NOT NULL AUTO_INCREMENT,
  `league` varchar(45) DEFAULT NULL,
  `owner_name` varchar(255) NOT NULL DEFAULT '',
  `gm_name` varchar(255) NOT NULL DEFAULT '',
  `manager_name` varchar(255) NOT NULL DEFAULT '',
  `scout_name` varchar(255) NOT NULL DEFAULT '',
  `coach` varchar(255) NOT NULL DEFAULT 'AI',
  PRIMARY KEY (`id`),
  KEY `fk_mlb` (`mlb`),
  KEY `fk_aaa` (`aaa`),
  KEY `fk_aa` (`aa`),
  KEY `fk_a` (`a`),
  KEY `fk_higha` (`higha`),
  KEY `fk_scraps` (`scraps`),
  CONSTRAINT `fk_a` FOREIGN KEY (`a`) REFERENCES `teams` (`id`),
  CONSTRAINT `fk_aa` FOREIGN KEY (`aa`) REFERENCES `teams` (`id`),
  CONSTRAINT `fk_aaa` FOREIGN KEY (`aaa`) REFERENCES `teams` (`id`),
  CONSTRAINT `fk_higha` FOREIGN KEY (`higha`) REFERENCES `teams` (`id`),
  CONSTRAINT `fk_mlb` FOREIGN KEY (`mlb`) REFERENCES `teams` (`id`),
  CONSTRAINT `fk_scraps` FOREIGN KEY (`scraps`) REFERENCES `teams` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=343 DEFAULT CHARSET=utf8mb3;
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

-- Dump completed on 2026-03-17 10:18:25
