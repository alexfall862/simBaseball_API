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
-- Temporary view structure for view `organization_report`
--

DROP TABLE IF EXISTS `organization_report`;
/*!50001 DROP VIEW IF EXISTS `organization_report`*/;
SET @saved_cs_client     = @@character_set_client;
/*!50503 SET character_set_client = utf8mb4 */;
/*!50001 CREATE VIEW `organization_report` AS SELECT 
 1 AS `id`,
 1 AS `org_abbrev`,
 1 AS `mlb_team_id`,
 1 AS `mlb_abbrev`,
 1 AS `mlb_city`,
 1 AS `mlb_nickname`,
 1 AS `mlb_full_name`,
 1 AS `aaa_team_id`,
 1 AS `aaa_abbrev`,
 1 AS `aaa_nickname`,
 1 AS `aaa_team_city`,
 1 AS `aaa_full_name`,
 1 AS `aa_team_id`,
 1 AS `aa_abbrev`,
 1 AS `aa_nickname`,
 1 AS `aa_team_city`,
 1 AS `aa_full_name`,
 1 AS `a_team_id`,
 1 AS `a_abbrev`,
 1 AS `a_nickname`,
 1 AS `a_team_city`,
 1 AS `a_full_name`,
 1 AS `higha_team_id`,
 1 AS `higha_abbrev`,
 1 AS `higha_nickname`,
 1 AS `higha_team_city`,
 1 AS `higha_full_name`,
 1 AS `scraps_team_id`,
 1 AS `scraps_abbrev`,
 1 AS `scraps_nickname`,
 1 AS `scraps_team_city`,
 1 AS `scraps_full_name`,
 1 AS `cash`*/;
SET character_set_client = @saved_cs_client;

--
-- Final view structure for view `organization_report`
--

/*!50001 DROP VIEW IF EXISTS `organization_report`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_0900_ai_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`root`@`%` SQL SECURITY DEFINER */
/*!50001 VIEW `organization_report` AS select `o`.`id` AS `id`,`o`.`org_abbrev` AS `org_abbrev`,`o`.`mlb` AS `mlb_team_id`,`mlb`.`team_abbrev` AS `mlb_abbrev`,`mlb`.`team_city` AS `mlb_city`,`mlb`.`team_nickname` AS `mlb_nickname`,concat(`mlb`.`team_city`,' ',`mlb`.`team_nickname`) AS `mlb_full_name`,`o`.`aaa` AS `aaa_team_id`,`aaa`.`team_abbrev` AS `aaa_abbrev`,`aaa`.`team_nickname` AS `aaa_nickname`,`aaa`.`team_city` AS `aaa_team_city`,concat(`aaa`.`team_city`,' ',`aaa`.`team_nickname`) AS `aaa_full_name`,`o`.`aa` AS `aa_team_id`,`aa`.`team_abbrev` AS `aa_abbrev`,`aa`.`team_nickname` AS `aa_nickname`,`aa`.`team_city` AS `aa_team_city`,concat(`aa`.`team_city`,' ',`aa`.`team_nickname`) AS `aa_full_name`,`o`.`a` AS `a_team_id`,`a`.`team_abbrev` AS `a_abbrev`,`a`.`team_nickname` AS `a_nickname`,`a`.`team_city` AS `a_team_city`,concat(`a`.`team_city`,' ',`a`.`team_nickname`) AS `a_full_name`,`o`.`higha` AS `higha_team_id`,`higha`.`team_abbrev` AS `higha_abbrev`,`higha`.`team_nickname` AS `higha_nickname`,`higha`.`team_city` AS `higha_team_city`,concat(`higha`.`team_city`,' ',`higha`.`team_nickname`) AS `higha_full_name`,`o`.`scraps` AS `scraps_team_id`,`scraps`.`team_abbrev` AS `scraps_abbrev`,`scraps`.`team_nickname` AS `scraps_nickname`,`scraps`.`team_city` AS `scraps_team_city`,concat(`scraps`.`team_city`,' ',`scraps`.`team_nickname`) AS `scraps_full_name`,`o`.`cash` AS `cash` from ((((((`organizations` `o` left join `teams` `mlb` on((`mlb`.`id` = `o`.`mlb`))) left join `teams` `aaa` on((`aaa`.`id` = `o`.`aaa`))) left join `teams` `aa` on((`aa`.`id` = `o`.`aa`))) left join `teams` `a` on((`a`.`id` = `o`.`a`))) left join `teams` `higha` on((`higha`.`id` = `o`.`higha`))) left join `teams` `scraps` on((`scraps`.`id` = `o`.`scraps`))) */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;
SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-11-21  2:26:47
