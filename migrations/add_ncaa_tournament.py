# migrations/add_ncaa_tournament.py
"""
Schema for the real NCAA-style 64-team college postseason (level 3).

Two idempotent changes:

  1. Create ``playoff_seeds`` if it is missing.  ``wipe_playoffs`` and the MLB
     bye-team logic reference this table; it was defined in
     ``migrations/add_playoff_seeds.sql`` but never applied to some databases,
     which made every level-3 wipe crash with
     ``(1146) Table '...playoff_seeds' doesn't exist``.

  2. Widen ``cws_bracket`` with the columns the multi-stage tournament needs to
     track a team through Regionals → Super Regionals → MCWS → Finals:
     ``national_seed``, ``regional_no``, ``regional_seed``, ``stage``.

Safe to run repeatedly — each step checks ``information_schema`` first.
"""

import logging

from sqlalchemy import text as sa_text

log = logging.getLogger("app")


_PLAYOFF_SEEDS_DDL = """
CREATE TABLE IF NOT EXISTS `playoff_seeds` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_year_id` int NOT NULL,
  `league_level` int NOT NULL,
  `conference` varchar(50) NOT NULL DEFAULT '',
  `seed` int NOT NULL,
  `team_id` int NOT NULL,
  `qualifier` varchar(30) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_playoff_seeds` (`league_year_id`, `league_level`, `conference`, `seed`)
) ENGINE=InnoDB
"""

# (column, DDL type) pairs added to cws_bracket if absent.
_CWS_COLUMNS = [
    ("national_seed", "int DEFAULT NULL"),
    ("regional_no", "int DEFAULT NULL"),
    ("regional_seed", "int DEFAULT NULL"),
    ("stage", "varchar(16) DEFAULT NULL"),
]


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(sa_text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = :t AND column_name = :c
        LIMIT 1
    """), {"t": table, "c": column}).first())


def migrate_add_ncaa_tournament(engine) -> dict:
    """Apply the NCAA-tournament schema.  Returns a summary of what changed."""
    result = {"playoff_seeds_created": False, "cws_columns_added": []}

    with engine.begin() as conn:
        # 1. playoff_seeds
        existed = bool(conn.execute(sa_text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = 'playoff_seeds'
            LIMIT 1
        """)).first())
        conn.execute(sa_text(_PLAYOFF_SEEDS_DDL))
        result["playoff_seeds_created"] = not existed

        # 2. cws_bracket columns
        for col, ddl in _CWS_COLUMNS:
            if not _column_exists(conn, "cws_bracket", col):
                conn.execute(sa_text(
                    f"ALTER TABLE `cws_bracket` ADD COLUMN `{col}` {ddl}"
                ))
                result["cws_columns_added"].append(col)

    log.info("migrate_add_ncaa_tournament: %s", result)
    return result
