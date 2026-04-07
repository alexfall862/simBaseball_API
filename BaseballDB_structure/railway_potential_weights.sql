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
-- Table structure for table `potential_weights`
--

DROP TABLE IF EXISTS `potential_weights`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `potential_weights` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_type` varchar(10) NOT NULL,
  `ability_class` varchar(15) NOT NULL,
  `grade` varchar(2) NOT NULL,
  `weight` float NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_type_class_grade` (`player_type`,`ability_class`,`grade`)
) ENGINE=InnoDB AUTO_INCREMENT=113 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `potential_weights`
--

LOCK TABLES `potential_weights` WRITE;
/*!40000 ALTER TABLE `potential_weights` DISABLE KEYS */;
INSERT INTO `potential_weights` VALUES (1,'Pitcher','PitchAbility','A+',5),(2,'Pitcher','PitchAbility','A',7.5),(3,'Pitcher','PitchAbility','A-',12.5),(4,'Pitcher','PitchAbility','B+',15),(5,'Pitcher','PitchAbility','B',17),(6,'Pitcher','PitchAbility','B-',18),(7,'Pitcher','PitchAbility','C+',22),(8,'Pitcher','PitchAbility','C',25),(9,'Pitcher','PitchAbility','C-',28),(10,'Pitcher','PitchAbility','D+',32),(11,'Pitcher','PitchAbility','D',33),(12,'Pitcher','PitchAbility','D-',35),(13,'Pitcher','PitchAbility','F',750),(14,'Pitcher','PitchAbility','N',0),(15,'Pitcher','CatchAbility','A+',0),(16,'Pitcher','CatchAbility','A',0),(17,'Pitcher','CatchAbility','A-',0),(18,'Pitcher','CatchAbility','B+',0),(19,'Pitcher','CatchAbility','B',0),(20,'Pitcher','CatchAbility','B-',0),(21,'Pitcher','CatchAbility','C+',0),(22,'Pitcher','CatchAbility','C',0),(23,'Pitcher','CatchAbility','C-',0),(24,'Pitcher','CatchAbility','D+',31),(25,'Pitcher','CatchAbility','D',33),(26,'Pitcher','CatchAbility','D-',35),(27,'Pitcher','CatchAbility','F',900),(28,'Pitcher','CatchAbility','N',0),(29,'Pitcher','Ability','A+',1),(30,'Pitcher','Ability','A',2),(31,'Pitcher','Ability','A-',3),(32,'Pitcher','Ability','B+',4),(33,'Pitcher','Ability','B',5),(34,'Pitcher','Ability','B-',6),(35,'Pitcher','Ability','C+',7),(36,'Pitcher','Ability','C',8),(37,'Pitcher','Ability','C-',9),(38,'Pitcher','Ability','D+',10),(39,'Pitcher','Ability','D',11),(40,'Pitcher','Ability','D-',12),(41,'Pitcher','Ability','F',152),(42,'Pitcher','Ability','N',770),(43,'Pitcher','ThrowAbility','A+',80),(44,'Pitcher','ThrowAbility','A',80),(45,'Pitcher','ThrowAbility','A-',90),(46,'Pitcher','ThrowAbility','B+',90),(47,'Pitcher','ThrowAbility','B',100),(48,'Pitcher','ThrowAbility','B-',110),(49,'Pitcher','ThrowAbility','C+',110),(50,'Pitcher','ThrowAbility','C',100),(51,'Pitcher','ThrowAbility','C-',90),(52,'Pitcher','ThrowAbility','D+',40),(53,'Pitcher','ThrowAbility','D',30),(54,'Pitcher','ThrowAbility','D-',30),(55,'Pitcher','ThrowAbility','F',5),(56,'Pitcher','ThrowAbility','N',0),(57,'Position','PitchAbility','A+',1),(58,'Position','PitchAbility','A',2),(59,'Position','PitchAbility','A-',3),(60,'Position','PitchAbility','B+',4),(61,'Position','PitchAbility','B',5),(62,'Position','PitchAbility','B-',6),(63,'Position','PitchAbility','C+',7),(64,'Position','PitchAbility','C',8),(65,'Position','PitchAbility','C-',9),(66,'Position','PitchAbility','D+',10),(67,'Position','PitchAbility','D',11),(68,'Position','PitchAbility','D-',12),(69,'Position','PitchAbility','F',152),(70,'Position','PitchAbility','N',770),(71,'Position','CatchAbility','A+',2.5),(72,'Position','CatchAbility','A',3.7),(73,'Position','CatchAbility','A-',6.3),(74,'Position','CatchAbility','B+',7.5),(75,'Position','CatchAbility','B',8.5),(76,'Position','CatchAbility','B-',9),(77,'Position','CatchAbility','C+',11),(78,'Position','CatchAbility','C',12.5),(79,'Position','CatchAbility','C-',14),(80,'Position','CatchAbility','D+',16),(81,'Position','CatchAbility','D',16.5),(82,'Position','CatchAbility','D-',17.5),(83,'Position','CatchAbility','F',875),(84,'Position','CatchAbility','N',0),(85,'Position','Ability','A+',5),(86,'Position','Ability','A',7.5),(87,'Position','Ability','A-',12.5),(88,'Position','Ability','B+',15),(89,'Position','Ability','B',17),(90,'Position','Ability','B-',18),(91,'Position','Ability','C+',22),(92,'Position','Ability','C',25),(93,'Position','Ability','C-',28),(94,'Position','Ability','D+',32),(95,'Position','Ability','D',33),(96,'Position','Ability','D-',35),(97,'Position','Ability','F',750),(98,'Position','Ability','N',0),(99,'Position','ThrowAbility','A+',5),(100,'Position','ThrowAbility','A',7.5),(101,'Position','ThrowAbility','A-',12.5),(102,'Position','ThrowAbility','B+',15),(103,'Position','ThrowAbility','B',17),(104,'Position','ThrowAbility','B-',18),(105,'Position','ThrowAbility','C+',22),(106,'Position','ThrowAbility','C',25),(107,'Position','ThrowAbility','C-',28),(108,'Position','ThrowAbility','D+',32),(109,'Position','ThrowAbility','D',33),(110,'Position','ThrowAbility','D-',35),(111,'Position','ThrowAbility','F',750),(112,'Position','ThrowAbility','N',0);
/*!40000 ALTER TABLE `potential_weights` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:13:44
