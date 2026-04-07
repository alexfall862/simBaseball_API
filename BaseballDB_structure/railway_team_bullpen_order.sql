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
-- Table structure for table `team_bullpen_order`
--

DROP TABLE IF EXISTS `team_bullpen_order`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `team_bullpen_order` (
  `id` int NOT NULL AUTO_INCREMENT,
  `team_id` int NOT NULL,
  `slot` int NOT NULL COMMENT '1-based ordering slot',
  `player_id` int NOT NULL,
  `role` enum('closer','setup','middle','long','mop_up') NOT NULL DEFAULT 'middle',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_bp_team_slot` (`team_id`,`slot`),
  KEY `fk_bp_player` (`player_id`),
  CONSTRAINT `fk_bp_player` FOREIGN KEY (`player_id`) REFERENCES `simbbPlayers` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_bp_team` FOREIGN KEY (`team_id`) REFERENCES `teams` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=304 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `team_bullpen_order`
--

LOCK TABLES `team_bullpen_order` WRITE;
/*!40000 ALTER TABLE `team_bullpen_order` DISABLE KEYS */;
INSERT INTO `team_bullpen_order` VALUES (4,1,1,49847,'closer'),(5,1,2,59488,'setup'),(6,1,3,50125,'middle'),(7,1,4,55566,'middle'),(8,1,5,47953,'long'),(9,1,6,54493,'long'),(10,1,7,36625,'long'),(11,1,8,56959,'mop_up'),(12,2,1,54185,'closer'),(13,2,2,50484,'setup'),(14,2,3,44008,'middle'),(15,2,4,66463,'middle'),(16,2,5,59253,'long'),(17,2,6,54370,'long'),(18,2,7,54604,'long'),(19,2,8,58626,'long'),(20,2,9,46189,'mop_up'),(21,3,1,57883,'closer'),(22,3,2,62897,'setup'),(23,3,3,53560,'middle'),(24,3,4,59919,'middle'),(25,3,5,46931,'long'),(26,3,6,47097,'long'),(27,3,7,59788,'long'),(28,3,8,58415,'long'),(29,3,9,52958,'mop_up'),(38,5,1,51518,'closer'),(39,5,2,51976,'setup'),(40,5,3,61585,'middle'),(41,5,4,49599,'middle'),(42,5,5,49426,'long'),(43,5,6,44702,'long'),(44,5,7,43904,'long'),(45,5,8,40578,'mop_up'),(46,6,1,49544,'closer'),(47,6,2,38249,'setup'),(48,6,3,61062,'middle'),(49,6,4,61549,'middle'),(50,6,5,58441,'long'),(51,6,6,56253,'long'),(52,6,7,53168,'long'),(53,6,8,58378,'long'),(54,6,9,51507,'long'),(55,6,10,54786,'mop_up'),(56,7,1,52495,'closer'),(57,7,2,59462,'setup'),(58,7,3,45366,'middle'),(59,7,4,46699,'middle'),(60,7,5,57834,'long'),(61,7,6,48838,'long'),(62,7,7,48954,'mop_up'),(63,8,1,55163,'closer'),(64,8,2,47437,'setup'),(65,8,3,54477,'middle'),(66,8,4,50127,'middle'),(67,8,5,60850,'long'),(68,8,6,59984,'long'),(69,8,7,49176,'long'),(70,8,8,52780,'mop_up'),(78,10,1,62504,'closer'),(79,10,2,51918,'setup'),(80,10,3,47864,'middle'),(81,10,4,47289,'middle'),(82,10,5,47543,'long'),(83,10,6,47960,'long'),(84,10,7,37209,'mop_up'),(85,11,1,53397,'closer'),(86,11,2,52182,'setup'),(87,11,3,45343,'middle'),(88,11,4,46978,'middle'),(89,11,5,34664,'long'),(90,11,6,64743,'long'),(91,11,7,58233,'long'),(92,11,8,42876,'mop_up'),(93,12,1,46394,'closer'),(94,12,2,44268,'setup'),(95,12,3,57318,'middle'),(96,12,4,53317,'middle'),(97,12,5,56438,'long'),(98,12,6,62197,'long'),(99,12,7,58545,'long'),(100,12,8,49692,'mop_up'),(101,13,1,62847,'closer'),(102,13,2,57519,'setup'),(103,13,3,68900,'middle'),(104,13,4,65571,'middle'),(105,13,5,43986,'long'),(106,13,6,43571,'long'),(107,13,7,62569,'long'),(108,13,8,62427,'mop_up'),(109,14,1,52579,'closer'),(110,14,2,48413,'setup'),(111,14,3,59621,'middle'),(112,14,4,56392,'middle'),(113,14,5,53254,'long'),(114,14,6,49136,'long'),(115,14,7,58129,'long'),(116,14,8,54455,'mop_up'),(117,15,1,55670,'closer'),(118,15,2,49064,'setup'),(119,15,3,39798,'middle'),(120,15,4,52369,'middle'),(121,15,5,52520,'long'),(122,15,6,50184,'long'),(123,15,7,53435,'long'),(124,15,8,43629,'mop_up'),(125,16,1,64330,'closer'),(126,16,2,54059,'setup'),(127,16,3,55527,'middle'),(128,16,4,40395,'middle'),(129,16,5,47524,'long'),(130,16,6,62971,'long'),(131,16,7,59487,'long'),(132,16,8,55710,'mop_up'),(133,17,1,65071,'closer'),(134,17,2,42004,'setup'),(135,17,3,63483,'middle'),(136,17,4,45355,'middle'),(137,17,5,60435,'long'),(138,17,6,55067,'long'),(139,17,7,66002,'long'),(140,17,8,48333,'mop_up'),(149,19,1,40167,'closer'),(150,19,2,51653,'setup'),(151,19,3,45484,'middle'),(152,19,4,54623,'middle'),(153,19,5,62985,'long'),(154,19,6,52480,'long'),(155,19,7,59113,'long'),(156,19,8,49267,'mop_up'),(165,21,1,35415,'closer'),(166,21,2,47809,'setup'),(167,21,3,44867,'middle'),(168,21,4,56868,'middle'),(169,21,5,47583,'long'),(170,21,6,52370,'long'),(171,21,7,55676,'long'),(172,21,8,45316,'mop_up'),(173,22,1,61443,'closer'),(174,22,2,47191,'setup'),(175,22,3,48378,'middle'),(176,22,4,54504,'middle'),(177,22,5,57910,'long'),(178,22,6,42169,'mop_up'),(179,23,1,39964,'closer'),(180,23,2,59936,'setup'),(181,23,3,49066,'middle'),(182,23,4,51693,'middle'),(183,23,5,46469,'long'),(184,23,6,57530,'long'),(185,23,7,44597,'long'),(186,23,8,57945,'mop_up'),(187,24,1,54019,'closer'),(188,24,2,60762,'setup'),(189,24,3,58051,'middle'),(190,24,4,51880,'middle'),(191,24,5,58479,'long'),(192,24,6,53489,'long'),(193,24,7,62448,'mop_up'),(194,25,1,48493,'closer'),(195,25,2,56412,'setup'),(196,25,3,57189,'middle'),(197,25,4,58850,'middle'),(198,25,5,52413,'long'),(199,25,6,50835,'long'),(200,25,7,58253,'mop_up'),(201,26,1,66827,'closer'),(202,26,2,54279,'setup'),(203,26,3,69946,'middle'),(204,26,4,40444,'middle'),(205,26,5,55638,'long'),(206,26,6,41513,'long'),(207,26,7,65085,'long'),(208,26,8,60465,'long'),(209,26,9,55761,'mop_up'),(210,27,1,55958,'closer'),(211,27,2,46407,'setup'),(212,27,3,47671,'middle'),(213,27,4,59774,'middle'),(214,27,5,55567,'long'),(215,27,6,45406,'long'),(216,27,7,36559,'long'),(217,27,8,45390,'long'),(218,27,9,62141,'mop_up'),(219,28,1,48571,'closer'),(220,28,2,49276,'setup'),(221,28,3,45912,'middle'),(222,28,4,40450,'middle'),(223,28,5,60143,'long'),(224,28,6,33721,'long'),(225,28,7,54203,'long'),(226,28,8,58844,'mop_up'),(235,30,1,56284,'closer'),(236,30,2,40211,'setup'),(237,30,3,59104,'middle'),(238,30,4,48251,'middle'),(239,30,5,63426,'long'),(240,30,6,58887,'long'),(241,30,7,62009,'long'),(242,30,8,46266,'long'),(243,30,9,58101,'mop_up'),(250,18,1,57041,'closer'),(251,18,2,57319,'middle'),(252,18,3,45853,'middle'),(253,18,4,47206,'middle'),(254,18,5,51355,'middle'),(262,29,1,60412,'closer'),(263,29,2,62610,'setup'),(264,29,3,60944,'middle'),(265,29,4,55933,'middle'),(266,29,5,61169,'long'),(267,29,6,63093,'long'),(268,29,7,49369,'long'),(269,29,8,48577,'mop_up'),(270,20,1,58888,'middle'),(271,20,2,46698,'setup'),(272,20,3,63023,'closer'),(273,20,4,68219,'long'),(274,20,5,67074,'long'),(275,20,6,47698,'setup'),(276,20,7,53967,'middle'),(277,20,8,51028,'mop_up'),(278,20,9,68661,'mop_up'),(289,4,1,62065,'closer'),(290,4,2,38553,'setup'),(291,4,3,41355,'middle'),(292,4,4,37603,'long'),(293,4,5,66672,'middle'),(294,4,6,50751,'mop_up'),(295,4,7,51684,'mop_up'),(296,4,8,60719,'mop_up'),(297,9,1,50907,'middle'),(298,9,2,59674,'long'),(299,9,3,53784,'mop_up'),(300,9,4,46706,'long'),(301,9,5,56247,'setup'),(302,9,6,47741,'middle'),(303,9,7,55913,'closer');
/*!40000 ALTER TABLE `team_bullpen_order` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:04:30
