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
-- Table structure for table `level_sim_config`
--

DROP TABLE IF EXISTS `level_sim_config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `level_sim_config` (
  `league_level` int NOT NULL,
  `baseline_outcomes_json` json NOT NULL,
  PRIMARY KEY (`league_level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `level_sim_config`
--

LOCK TABLES `level_sim_config` WRITE;
/*!40000 ALTER TABLE `level_sim_config` DISABLE KEYS */;
INSERT INTO `level_sim_config` VALUES (1,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}'),(2,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}'),(3,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}'),(4,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}'),(5,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}'),(6,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}'),(7,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}'),(8,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}'),(9,'{\"modexp\": 2, \"c_weakodds\": 0.4, \"error_rate\": 0.05, \"InsideSwing\": 0.65, \"c_flareodds\": 36.0, \"c_solidodds\": 12.0, \"c_underodds\": 2.4, \"OutsideSwing\": 0.3, \"c_barrelodds\": 7.0, \"c_burnerodds\": 39.0, \"c_toppedodds\": 3.2, \"InsideContact\": 0.87, \"steal_success\": 0.65, \"OutsideContact\": 0.66, \"pickoff_success\": 0.1, \"ingame_injury_base_rate\": 0.1, \"pregame_injury_base_rate\": 0.1}');
/*!40000 ALTER TABLE `level_sim_config` ENABLE KEYS */;
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

-- Dump completed on 2025-11-21  2:26:22
