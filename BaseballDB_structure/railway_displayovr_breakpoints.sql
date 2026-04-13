--
-- Table structure for table `displayovr_breakpoints`
--
-- Stores league-wide raw_ovr cutoffs per (level, rating_type) for the
-- canonical displayovr / position-rating percentile-rank pipeline.
-- All player types (Pitcher + Position) are pooled together per level.
--
-- Refreshed by:
--   * services/ovr_core.recompute_stored_displayovr()
--   * Admin weight profile activation
--   * Manual admin recompute endpoint
--   * Engine subweek processing
--
-- rating_type values:
--   'displayovr' -- listed-position overall (the player's own position)
--   'c_rating', 'fb_rating', ... 'rp_rating' -- per-position ratings
--

DROP TABLE IF EXISTS `displayovr_breakpoints`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `displayovr_breakpoints` (
  `level` int NOT NULL,
  `ptype` varchar(16) NOT NULL DEFAULT 'ALL',
  `rating_type` varchar(32) NOT NULL DEFAULT 'displayovr',
  `raw_overalls_json` longtext NOT NULL,
  `player_count` int NOT NULL,
  `computed_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`level`, `ptype`, `rating_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
/*!40101 SET character_set_client = @saved_cs_client */;
