-- Unify pregame + ingame injuries in one table with explicit source attribution.
--
-- Run order:
--   1) ALTER to add the column (default 'ingame' keeps existing rows correct
--      for the overwhelming majority — no pregame injuries have been persisted
--      historically because random_seed was NULL on every game).
--   2) Backfill via join on injury_types.timeframe for any rows that happen to
--      reference a pregame injury_type_id.
--   3) Add the idempotency index used by the result-ingest path.

ALTER TABLE player_injury_events
    ADD COLUMN source ENUM('pregame','ingame') NOT NULL DEFAULT 'ingame'
    AFTER gamelist_id;

UPDATE player_injury_events pie
JOIN injury_types it ON it.id = pie.injury_type_id
SET pie.source = 'pregame'
WHERE it.timeframe = 'pregame';

-- Idempotency guard for result ingestion: a given player can only have one
-- injury of a given type persisted per game. Enforced at the DB layer so a
-- replay or an engine echo can't produce duplicates.
--
-- NULL gamelist_id is allowed (legacy rows pre-fix), and MySQL treats NULL as
-- distinct in unique indexes so those rows won't collide.
ALTER TABLE player_injury_events
    ADD UNIQUE KEY uq_pie_game_player_type (gamelist_id, player_id, injury_type_id);
