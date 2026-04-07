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
-- Table structure for table `rating_overall_weights`
--

DROP TABLE IF EXISTS `rating_overall_weights`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `rating_overall_weights` (
  `id` int NOT NULL AUTO_INCREMENT,
  `rating_type` varchar(50) NOT NULL,
  `attribute_key` varchar(50) NOT NULL,
  `weight` float NOT NULL DEFAULT '0',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_overall_weight` (`rating_type`,`attribute_key`)
) ENGINE=InnoDB AUTO_INCREMENT=1265 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `rating_overall_weights`
--

LOCK TABLES `rating_overall_weights` WRITE;
/*!40000 ALTER TABLE `rating_overall_weights` DISABLE KEYS */;
INSERT INTO `rating_overall_weights` VALUES (1,'position_overall','power_base',0.1,'2026-03-17 16:37:10'),(2,'position_overall','contact_base',0.1,'2026-03-17 16:37:10'),(3,'position_overall','discipline_base',0.1,'2026-03-17 16:37:10'),(4,'position_overall','eye_base',0.1,'2026-03-17 16:37:10'),(5,'position_overall','speed_base',0.1,'2026-03-17 16:37:10'),(6,'position_overall','baserunning_base',0,'2026-03-17 16:37:10'),(7,'position_overall','basereaction_base',0,'2026-03-17 16:37:10'),(8,'position_overall','throwacc_base',0.1,'2026-03-17 16:37:10'),(9,'position_overall','throwpower_base',0.1,'2026-03-17 16:37:10'),(10,'position_overall','fieldcatch_base',0.1,'2026-03-17 16:37:10'),(11,'position_overall','fieldreact_base',0.1,'2026-03-17 16:37:10'),(12,'position_overall','fieldspot_base',0.1,'2026-03-17 16:37:10'),(13,'position_overall','catchframe_base',0,'2026-03-17 16:37:10'),(14,'position_overall','catchsequence_base',0,'2026-03-17 16:37:10'),(15,'pitcher_overall','pendurance_base',0.2,'2026-03-17 16:37:09'),(16,'pitcher_overall','pgencontrol_base',0.2,'2026-03-17 16:37:09'),(17,'pitcher_overall','psequencing_base',0.1,'2026-03-17 16:37:10'),(18,'pitcher_overall','pthrowpower_base',0.2,'2026-03-17 16:37:10'),(19,'pitcher_overall','pickoff_base',0.05,'2026-03-17 16:37:09'),(20,'pitcher_overall','fieldcatch_base',0,'2026-03-17 16:37:09'),(21,'pitcher_overall','fieldreact_base',0,'2026-03-17 16:37:09'),(22,'pitcher_overall','fieldspot_base',0,'2026-03-17 16:37:09'),(23,'pitcher_overall','pitch1_ovr',0.05,'2026-03-17 16:37:09'),(24,'pitcher_overall','pitch2_ovr',0.05,'2026-03-17 16:37:09'),(25,'pitcher_overall','pitch3_ovr',0.05,'2026-03-17 16:37:09'),(26,'pitcher_overall','pitch4_ovr',0.05,'2026-03-17 16:37:09'),(27,'pitcher_overall','pitch5_ovr',0.05,'2026-03-17 16:37:09'),(123,'dh_rating','power_base',0.22,'2026-03-17 16:37:08'),(124,'dh_rating','contact_base',0.22,'2026-03-17 16:37:08'),(125,'dh_rating','eye_base',0.22,'2026-03-17 16:37:08'),(126,'dh_rating','discipline_base',0.22,'2026-03-17 16:37:08'),(127,'dh_rating','basereaction_base',0,'2026-03-17 16:37:07'),(128,'dh_rating','baserunning_base',0,'2026-03-17 16:37:08'),(129,'dh_rating','speed_base',0.12,'2026-03-17 16:37:08'),(987,'cf_rating','basereaction_base',0,'2026-03-17 16:37:07'),(988,'cf_rating','baserunning_base',0,'2026-03-17 16:37:07'),(989,'cf_rating','contact_base',0.1,'2026-03-17 16:37:07'),(990,'cf_rating','discipline_base',0.1,'2026-03-17 16:37:07'),(991,'cf_rating','eye_base',0.1,'2026-03-17 16:37:07'),(992,'cf_rating','fieldcatch_base',0.15,'2026-03-17 16:37:07'),(993,'cf_rating','fieldreact_base',0.1,'2026-03-17 16:37:07'),(994,'cf_rating','fieldspot_base',0.15,'2026-03-17 16:37:07'),(995,'cf_rating','power_base',0.1,'2026-03-17 16:37:07'),(996,'cf_rating','speed_base',0.1,'2026-03-17 16:37:07'),(997,'cf_rating','throwacc_base',0.05,'2026-03-17 16:37:07'),(998,'cf_rating','throwpower_base',0.05,'2026-03-17 16:37:07'),(999,'c_rating','basereaction_base',0,'2026-03-17 16:37:06'),(1000,'c_rating','baserunning_base',0,'2026-03-17 16:37:06'),(1001,'c_rating','catchframe_base',0.15,'2026-03-17 16:37:06'),(1002,'c_rating','catchsequence_base',0.15,'2026-03-17 16:37:06'),(1003,'c_rating','contact_base',0.1,'2026-03-17 16:37:06'),(1004,'c_rating','discipline_base',0.1,'2026-03-17 16:37:06'),(1005,'c_rating','eye_base',0.1,'2026-03-17 16:37:07'),(1006,'c_rating','fieldcatch_base',0.05,'2026-03-17 16:37:07'),(1007,'c_rating','fieldreact_base',0.1,'2026-03-17 16:37:07'),(1008,'c_rating','fieldspot_base',0.05,'2026-03-17 16:37:07'),(1009,'c_rating','power_base',0.1,'2026-03-17 16:37:07'),(1010,'c_rating','speed_base',0,'2026-03-17 16:37:07'),(1011,'c_rating','throwacc_base',0.05,'2026-03-17 16:37:07'),(1012,'c_rating','throwpower_base',0.05,'2026-03-17 16:37:07'),(1013,'fb_rating','basereaction_base',0,'2026-03-17 16:37:08'),(1014,'fb_rating','baserunning_base',0,'2026-03-17 16:37:08'),(1015,'fb_rating','contact_base',0.1,'2026-03-17 16:37:08'),(1016,'fb_rating','discipline_base',0.1,'2026-03-17 16:37:08'),(1017,'fb_rating','eye_base',0.1,'2026-03-17 16:37:08'),(1018,'fb_rating','fieldcatch_base',0.3,'2026-03-17 16:37:08'),(1019,'fb_rating','fieldreact_base',0.15,'2026-03-17 16:37:08'),(1020,'fb_rating','fieldspot_base',0.05,'2026-03-17 16:37:08'),(1021,'fb_rating','power_base',0.1,'2026-03-17 16:37:08'),(1022,'fb_rating','speed_base',0,'2026-03-17 16:37:08'),(1023,'fb_rating','throwacc_base',0.1,'2026-03-17 16:37:08'),(1024,'fb_rating','throwpower_base',0,'2026-03-17 16:37:08'),(1025,'lf_rating','basereaction_base',0,'2026-03-17 16:37:08'),(1026,'lf_rating','baserunning_base',0,'2026-03-17 16:37:08'),(1027,'lf_rating','contact_base',0.1,'2026-03-17 16:37:09'),(1028,'lf_rating','discipline_base',0.1,'2026-03-17 16:37:09'),(1029,'lf_rating','eye_base',0.1,'2026-03-17 16:37:09'),(1030,'lf_rating','fieldcatch_base',0.15,'2026-03-17 16:37:09'),(1031,'lf_rating','fieldreact_base',0.1,'2026-03-17 16:37:09'),(1032,'lf_rating','fieldspot_base',0.15,'2026-03-17 16:37:09'),(1033,'lf_rating','power_base',0.1,'2026-03-17 16:37:09'),(1034,'lf_rating','speed_base',0.05,'2026-03-17 16:37:09'),(1035,'lf_rating','throwacc_base',0.1,'2026-03-17 16:37:09'),(1036,'lf_rating','throwpower_base',0.05,'2026-03-17 16:37:09'),(1037,'rf_rating','basereaction_base',0,'2026-03-17 16:37:10'),(1038,'rf_rating','baserunning_base',0,'2026-03-17 16:37:10'),(1039,'rf_rating','contact_base',0.1,'2026-03-17 16:37:10'),(1040,'rf_rating','discipline_base',0.1,'2026-03-17 16:37:10'),(1041,'rf_rating','eye_base',0.1,'2026-03-17 16:37:11'),(1042,'rf_rating','fieldcatch_base',0.15,'2026-03-17 16:37:11'),(1043,'rf_rating','fieldreact_base',0.1,'2026-03-17 16:37:11'),(1044,'rf_rating','fieldspot_base',0.15,'2026-03-17 16:37:11'),(1045,'rf_rating','power_base',0.1,'2026-03-17 16:37:11'),(1046,'rf_rating','speed_base',0.05,'2026-03-17 16:37:11'),(1047,'rf_rating','throwacc_base',0.05,'2026-03-17 16:37:11'),(1048,'rf_rating','throwpower_base',0.1,'2026-03-17 16:37:11'),(1049,'rp_rating','avg_consist',0.01,'2026-03-17 16:37:11'),(1050,'rp_rating','avg_pacc',0.01,'2026-03-17 16:37:11'),(1051,'rp_rating','avg_pbrk',0.01,'2026-03-17 16:37:11'),(1052,'rp_rating','avg_pcntrl',0.01,'2026-03-17 16:37:11'),(1053,'rp_rating','fieldcatch_base',0,'2026-03-17 16:37:11'),(1054,'rp_rating','fieldreact_base',0,'2026-03-17 16:37:11'),(1055,'rp_rating','fieldspot_base',0,'2026-03-17 16:37:11'),(1056,'rp_rating','pendurance_base',0.05,'2026-03-17 16:37:11'),(1057,'rp_rating','pgencontrol_base',0.2,'2026-03-17 16:37:11'),(1058,'rp_rating','pickoff_base',0.05,'2026-03-17 16:37:11'),(1059,'rp_rating','psequencing_base',0.16,'2026-03-17 16:37:11'),(1060,'rp_rating','pthrowpower_base',0.5,'2026-03-17 16:37:11'),(1061,'sb_rating','basereaction_base',0,'2026-03-17 16:37:11'),(1062,'sb_rating','baserunning_base',0,'2026-03-17 16:37:12'),(1063,'sb_rating','contact_base',0.1,'2026-03-17 16:37:12'),(1064,'sb_rating','discipline_base',0.1,'2026-03-17 16:37:12'),(1065,'sb_rating','eye_base',0.1,'2026-03-17 16:37:12'),(1066,'sb_rating','fieldcatch_base',0.15,'2026-03-17 16:37:12'),(1067,'sb_rating','fieldreact_base',0.15,'2026-03-17 16:37:12'),(1068,'sb_rating','fieldspot_base',0.05,'2026-03-17 16:37:12'),(1069,'sb_rating','power_base',0.1,'2026-03-17 16:37:12'),(1070,'sb_rating','speed_base',0.05,'2026-03-17 16:37:12'),(1071,'sb_rating','throwacc_base',0.175,'2026-03-17 16:37:12'),(1072,'sb_rating','throwpower_base',0.025,'2026-03-17 16:37:12'),(1073,'sp_rating','avg_consist',0.01,'2026-03-17 16:37:12'),(1074,'sp_rating','avg_pacc',0.01,'2026-03-17 16:37:12'),(1075,'sp_rating','avg_pbrk',0.01,'2026-03-17 16:37:12'),(1076,'sp_rating','avg_pcntrl',0.01,'2026-03-17 16:37:12'),(1077,'sp_rating','fieldcatch_base',0,'2026-03-17 16:37:12'),(1078,'sp_rating','fieldreact_base',0,'2026-03-17 16:37:12'),(1079,'sp_rating','fieldspot_base',0,'2026-03-17 16:37:12'),(1080,'sp_rating','pendurance_base',0.4,'2026-03-17 16:37:12'),(1081,'sp_rating','pgencontrol_base',0.2,'2026-03-17 16:37:12'),(1082,'sp_rating','pickoff_base',0.05,'2026-03-17 16:37:13'),(1083,'sp_rating','psequencing_base',0.05,'2026-03-17 16:37:13'),(1084,'sp_rating','pthrowpower_base',0.26,'2026-03-17 16:37:13'),(1085,'ss_rating','basereaction_base',0,'2026-03-17 16:37:13'),(1086,'ss_rating','baserunning_base',0,'2026-03-17 16:37:13'),(1087,'ss_rating','contact_base',0.1,'2026-03-17 16:37:13'),(1088,'ss_rating','discipline_base',0.1,'2026-03-17 16:37:13'),(1089,'ss_rating','eye_base',0.1,'2026-03-17 16:37:13'),(1090,'ss_rating','fieldcatch_base',0.15,'2026-03-17 16:37:13'),(1091,'ss_rating','fieldreact_base',0.15,'2026-03-17 16:37:13'),(1092,'ss_rating','fieldspot_base',0.05,'2026-03-17 16:37:13'),(1093,'ss_rating','power_base',0.1,'2026-03-17 16:37:13'),(1094,'ss_rating','speed_base',0.05,'2026-03-17 16:37:13'),(1095,'ss_rating','throwacc_base',0.05,'2026-03-17 16:37:13'),(1096,'ss_rating','throwpower_base',0.15,'2026-03-17 16:37:13'),(1097,'tb_rating','basereaction_base',0,'2026-03-17 16:37:13'),(1098,'tb_rating','baserunning_base',0,'2026-03-17 16:37:13'),(1099,'tb_rating','contact_base',0.1,'2026-03-17 16:37:13'),(1100,'tb_rating','discipline_base',0.1,'2026-03-17 16:37:13'),(1101,'tb_rating','eye_base',0.1,'2026-03-17 16:37:13'),(1102,'tb_rating','fieldcatch_base',0.1,'2026-03-17 16:37:13'),(1103,'tb_rating','fieldreact_base',0.15,'2026-03-17 16:37:14'),(1104,'tb_rating','fieldspot_base',0.05,'2026-03-17 16:37:14'),(1105,'tb_rating','power_base',0.1,'2026-03-17 16:37:14'),(1106,'tb_rating','speed_base',0,'2026-03-17 16:37:14'),(1107,'tb_rating','throwacc_base',0.1,'2026-03-17 16:37:14'),(1108,'tb_rating','throwpower_base',0.2,'2026-03-17 16:37:14');
/*!40000 ALTER TABLE `rating_overall_weights` ENABLE KEYS */;
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

-- Dump completed on 2026-03-29  0:03:45
