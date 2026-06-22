# services/awards.py
"""
Awards system — durable, cross-season record of player trophies and All-Star
selections (MVP, Cy Young, Silver Slugger, Gold Glove, ...).

Winners are entered by an admin/commissioner (POST /awards); this module is the
persistence + read layer, plus a hook the All-Star flow calls to record
selections as `all_star` awards so they survive independently of the
(wipe-able) special_events tables.

Public API:
    ensure_awards_schema(conn)                  — idempotent DDL + seed
    list_award_types(conn)                      — reference data for the UI
    record_award(conn, ...)                     — create/replace one award row
    revoke_award(conn, award_id)                — delete one award row
    record_all_star_selections(conn, ...)       — bulk-insert all_star awards
    get_player_awards(conn, player_id)          — one player's career awards
    get_awards_for_players_bulk(conn, ids)      — embed awards in list endpoints
    get_season_awards(conn, league_year_id)     — a season's full award slate
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text

log = logging.getLogger("app")

# Awards are issued at the MLB level today. league_level is still stored per-row,
# so enabling MiLB later is a one-line change here (no schema migration needed).
AWARD_LEAGUE_LEVELS = {9}
DEFAULT_AWARD_LEVEL = 9

VALID_SUB_LEAGUES = {"", "AL", "NL"}

_schema_ready = False


# =====================================================================
# Schema bootstrap (no migration runner in this project)
# =====================================================================

def ensure_awards_schema(conn) -> None:
    """Create award_types / player_awards and seed the trophy set if absent.

    Idempotent and cheap after the first call (guarded by a module flag).
    Mirrors migrations/add_awards_tables.sql — keep the two in sync.

    Runs in its OWN committed transaction (a fresh connection from the pool),
    not the caller's `conn`. This matters because some callers are read-only
    (engine.connect(), e.g. /stats/player): there the seed DML would otherwise
    roll back while the DDL auto-committed, leaving award_types empty and the
    FK from player_awards unsatisfiable. The bootstrap touches only the awards
    tables, so it can't conflict with the caller's in-flight transaction.
    """
    global _schema_ready
    if _schema_ready:
        return

    with conn.engine.begin() as c:
        _create_and_seed(c)

    _schema_ready = True


def _create_and_seed(conn) -> None:
    conn.execute(sa_text("""
        CREATE TABLE IF NOT EXISTS `award_types` (
          `code`             varchar(40)  NOT NULL,
          `name`             varchar(80)  NOT NULL,
          `category`         varchar(20)  NOT NULL DEFAULT 'major',
          `ptype_scope`      varchar(10)  NOT NULL DEFAULT 'any',
          `has_league_split` tinyint      NOT NULL DEFAULT 1,
          `is_per_position`  tinyint      NOT NULL DEFAULT 0,
          `allows_multiple`  tinyint      NOT NULL DEFAULT 0,
          `sort_order`       int          NOT NULL DEFAULT 100,
          `description`      varchar(255) DEFAULT NULL,
          PRIMARY KEY (`code`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """))

    conn.execute(sa_text("""
        CREATE TABLE IF NOT EXISTS `player_awards` (
          `id`             bigint        NOT NULL AUTO_INCREMENT,
          `player_id`      bigint unsigned NOT NULL,
          `league_year_id` int           NOT NULL,
          `league_level`   int           NOT NULL DEFAULT 9,
          `award_code`     varchar(40)   NOT NULL,
          `sub_league`     varchar(10)   NOT NULL DEFAULT '',
          `position_code`  varchar(10)   NOT NULL DEFAULT '',
          `team_id`        int           DEFAULT NULL,
          `rank`           tinyint       NOT NULL DEFAULT 1,
          `is_winner`      tinyint       NOT NULL DEFAULT 1,
          `vote_points`    decimal(10,2) DEFAULT NULL,
          `vote_share`     decimal(5,4)  DEFAULT NULL,
          `metadata_json`  json          DEFAULT NULL,
          `created_by`     varchar(80)   DEFAULT NULL,
          `created_at`     datetime      NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (`id`),
          UNIQUE KEY `uq_award_slot`
            (`league_year_id`,`league_level`,`award_code`,`sub_league`,`position_code`,`player_id`),
          KEY `idx_player` (`player_id`),
          KEY `idx_season` (`league_year_id`,`league_level`),
          KEY `idx_award` (`award_code`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """))

    # Seed / refresh the standard trophy set.
    for t in _AWARD_TYPES_SEED:
        conn.execute(sa_text("""
            INSERT INTO award_types
                (code, name, category, ptype_scope, has_league_split,
                 is_per_position, allows_multiple, sort_order, description)
            VALUES
                (:code, :name, :category, :ptype_scope, :has_league_split,
                 :is_per_position, :allows_multiple, :sort_order, :description)
            ON DUPLICATE KEY UPDATE
                name=VALUES(name), category=VALUES(category),
                ptype_scope=VALUES(ptype_scope),
                has_league_split=VALUES(has_league_split),
                is_per_position=VALUES(is_per_position),
                allows_multiple=VALUES(allows_multiple),
                sort_order=VALUES(sort_order), description=VALUES(description)
        """), t)


_AWARD_TYPES_SEED: List[Dict[str, Any]] = [
    {"code": "mvp", "name": "Most Valuable Player", "category": "major",
     "ptype_scope": "any", "has_league_split": 1, "is_per_position": 0,
     "allows_multiple": 0, "sort_order": 10,
     "description": "Most valuable player in each league."},
    {"code": "cy_young", "name": "Cy Young Award", "category": "pitching",
     "ptype_scope": "pitcher", "has_league_split": 1, "is_per_position": 0,
     "allows_multiple": 0, "sort_order": 20,
     "description": "Best pitcher in each league."},
    {"code": "roy", "name": "Rookie of the Year", "category": "major",
     "ptype_scope": "any", "has_league_split": 1, "is_per_position": 0,
     "allows_multiple": 0, "sort_order": 30,
     "description": "Best first-year player in each league."},
    {"code": "reliever", "name": "Reliever of the Year", "category": "pitching",
     "ptype_scope": "pitcher", "has_league_split": 1, "is_per_position": 0,
     "allows_multiple": 0, "sort_order": 40,
     "description": "Best relief pitcher in each league."},
    {"code": "comeback", "name": "Comeback Player", "category": "major",
     "ptype_scope": "any", "has_league_split": 1, "is_per_position": 0,
     "allows_multiple": 0, "sort_order": 50,
     "description": "Comeback Player of the Year in each league."},
    {"code": "silver_slugger", "name": "Silver Slugger", "category": "batting",
     "ptype_scope": "hitter", "has_league_split": 1, "is_per_position": 1,
     "allows_multiple": 0, "sort_order": 60,
     "description": "Best offensive player at each position in each league."},
    {"code": "gold_glove", "name": "Gold Glove", "category": "fielding",
     "ptype_scope": "any", "has_league_split": 1, "is_per_position": 1,
     "allows_multiple": 0, "sort_order": 70,
     "description": "Best defender at each position in each league."},
    {"code": "all_star", "name": "All-Star Selection", "category": "selection",
     "ptype_scope": "any", "has_league_split": 1, "is_per_position": 0,
     "allows_multiple": 1, "sort_order": 90,
     "description": "Selected to the league All-Star roster."},
]


# =====================================================================
# Reference data
# =====================================================================

def list_award_types(conn) -> List[Dict[str, Any]]:
    """Return the catalog of award types (for UI labels / dropdowns)."""
    ensure_awards_schema(conn)
    rows = conn.execute(sa_text("""
        SELECT code, name, category, ptype_scope, has_league_split,
               is_per_position, allows_multiple, sort_order, description
        FROM award_types
        ORDER BY sort_order, name
    """)).mappings().all()
    return [{
        "code": r["code"],
        "name": r["name"],
        "category": r["category"],
        "ptype_scope": r["ptype_scope"],
        "has_league_split": bool(r["has_league_split"]),
        "is_per_position": bool(r["is_per_position"]),
        "allows_multiple": bool(r["allows_multiple"]),
        "sort_order": int(r["sort_order"]),
        "description": r["description"],
    } for r in rows]


def _get_award_type(conn, award_code: str) -> Optional[Dict[str, Any]]:
    return conn.execute(sa_text("""
        SELECT code, name, has_league_split, is_per_position, allows_multiple
        FROM award_types WHERE code = :code
    """), {"code": award_code}).mappings().first()


def _snapshot_team_id(conn, player_id: int) -> Optional[int]:
    """Player's current active-contract team, for denormalized display."""
    return conn.execute(sa_text("""
        SELECT team_id FROM contracts
        WHERE player_id = :pid AND status = 'active'
        LIMIT 1
    """), {"pid": player_id}).scalar()


# =====================================================================
# Writes
# =====================================================================

def record_award(
    conn,
    player_id: int,
    league_year_id: int,
    award_code: str,
    sub_league: str = "",
    position_code: str = "",
    rank: int = 1,
    is_winner: Optional[bool] = None,
    league_level: int = DEFAULT_AWARD_LEVEL,
    team_id: Optional[int] = None,
    vote_points: Optional[float] = None,
    vote_share: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record (or update) a single award for a player in a season.

    Validates against the award_type config:
      - award_code must exist
      - split awards require sub_league in {AL,NL}; non-split forbid it
      - per-position awards require a position_code; others forbid it
      - single-winner awards (allows_multiple=0): recording a new winner at a
        given slot replaces any existing winner at that slot, so there is never
        more than one winner per (season, award, league, position).

    Upserts on uq_award_slot, so re-recording the same player is idempotent.
    """
    ensure_awards_schema(conn)

    atype = _get_award_type(conn, award_code)
    if not atype:
        raise ValueError(f"unknown award_code '{award_code}'")

    if int(league_level) not in AWARD_LEAGUE_LEVELS:
        raise ValueError(f"awards are only issued at levels {sorted(AWARD_LEAGUE_LEVELS)} "
                         f"(got {league_level})")

    sub_league = (sub_league or "").upper().strip()
    if sub_league not in VALID_SUB_LEAGUES:
        raise ValueError(f"invalid sub_league '{sub_league}'")
    if atype["has_league_split"] and not sub_league:
        raise ValueError(f"award '{award_code}' requires a sub_league (AL/NL)")
    if not atype["has_league_split"] and sub_league:
        raise ValueError(f"award '{award_code}' is league-wide; sub_league must be empty")

    position_code = (position_code or "").upper().strip()
    if atype["is_per_position"] and not position_code:
        raise ValueError(f"award '{award_code}' requires a position_code")
    if not atype["is_per_position"] and position_code:
        raise ValueError(f"award '{award_code}' is not per-position; position_code must be empty")

    rank = int(rank)
    if is_winner is None:
        is_winner = (rank == 1)

    if team_id is None:
        team_id = _snapshot_team_id(conn, player_id)

    # For single-winner awards, clear any prior winner occupying this exact slot
    # (different player) so we never end up with two winners.
    if not atype["allows_multiple"] and is_winner:
        conn.execute(sa_text("""
            DELETE FROM player_awards
            WHERE league_year_id = :ly AND league_level = :lvl
              AND award_code = :code AND sub_league = :sub
              AND position_code = :pos AND `rank` = :rank
              AND player_id <> :pid
        """), {
            "ly": league_year_id, "lvl": league_level, "code": award_code,
            "sub": sub_league, "pos": position_code, "rank": rank, "pid": player_id,
        })

    conn.execute(sa_text("""
        INSERT INTO player_awards
            (player_id, league_year_id, league_level, award_code, sub_league,
             position_code, team_id, `rank`, is_winner, vote_points, vote_share,
             metadata_json, created_by)
        VALUES
            (:pid, :ly, :lvl, :code, :sub, :pos, :team, :rank, :winner,
             :vpoints, :vshare, :meta, :by)
        ON DUPLICATE KEY UPDATE
            team_id=VALUES(team_id), `rank`=VALUES(`rank`),
            is_winner=VALUES(is_winner), vote_points=VALUES(vote_points),
            vote_share=VALUES(vote_share), metadata_json=VALUES(metadata_json),
            created_by=VALUES(created_by)
    """), {
        "pid": int(player_id), "ly": int(league_year_id), "lvl": int(league_level),
        "code": award_code, "sub": sub_league, "pos": position_code,
        "team": int(team_id) if team_id is not None else None,
        "rank": rank, "winner": 1 if is_winner else 0,
        "vpoints": vote_points, "vshare": vote_share,
        "meta": json.dumps(metadata) if metadata is not None else None,
        "by": created_by,
    })

    award_id = conn.execute(sa_text("""
        SELECT id FROM player_awards
        WHERE league_year_id = :ly AND league_level = :lvl AND award_code = :code
          AND sub_league = :sub AND position_code = :pos AND player_id = :pid
    """), {
        "ly": league_year_id, "lvl": league_level, "code": award_code,
        "sub": sub_league, "pos": position_code, "pid": player_id,
    }).scalar()

    log.info("awards: recorded %s (%s/%s) for player %d, season %d",
             award_code, sub_league or "-", position_code or "-",
             player_id, league_year_id)

    return {"award_id": int(award_id), "award_code": award_code,
            "player_id": int(player_id), "league_year_id": int(league_year_id)}


def revoke_award(conn, award_id: int) -> bool:
    """Delete a single award row. Returns True if a row was removed."""
    ensure_awards_schema(conn)
    res = conn.execute(sa_text("DELETE FROM player_awards WHERE id = :id"),
                       {"id": int(award_id)})
    return (res.rowcount or 0) > 0


def record_all_star_selections(
    conn,
    league_year_id: int,
    league_level: int,
    selections_by_label: Dict[str, List[int]],
) -> int:
    """
    Record All-Star roster selections as durable `all_star` awards.

    selections_by_label maps team_label ("AL"/"NL") -> list of player_ids.
    Every selected player gets an all_star award (is_winner=1, multiple allowed).
    Idempotent via uq_award_slot. Only issued for in-scope levels (MLB today).

    Returns the number of selections recorded.
    """
    if int(league_level) not in AWARD_LEAGUE_LEVELS:
        log.info("awards: skipping all_star record for level %d (out of scope)", league_level)
        return 0

    ensure_awards_schema(conn)
    count = 0
    for label, player_ids in selections_by_label.items():
        sub_league = (label or "").upper().strip()
        if sub_league not in ("AL", "NL"):
            # All-Star awards mirror MLB's AL/NL split; skip non-conforming labels.
            log.warning("awards: all_star label '%s' is not AL/NL; skipping", label)
            continue
        for pid in player_ids:
            team_id = _snapshot_team_id(conn, int(pid))
            conn.execute(sa_text("""
                INSERT INTO player_awards
                    (player_id, league_year_id, league_level, award_code,
                     sub_league, position_code, team_id, `rank`, is_winner, created_by)
                VALUES
                    (:pid, :ly, :lvl, 'all_star', :sub, '', :team, 1, 1, 'allstar_event')
                ON DUPLICATE KEY UPDATE team_id=VALUES(team_id)
            """), {
                "pid": int(pid), "ly": int(league_year_id),
                "lvl": int(league_level), "sub": sub_league, "team": team_id,
            })
            count += 1

    log.info("awards: recorded %d all_star selections for season %d",
             count, league_year_id)
    return count


# =====================================================================
# Reads
# =====================================================================

def _row_to_award(r) -> Dict[str, Any]:
    return {
        "award_id": int(r["id"]),
        "award_code": r["award_code"],
        "award_name": r["award_name"],
        "category": r["category"],
        "league_year_id": int(r["league_year_id"]),
        "league_level": int(r["league_level"]),
        "sub_league": r["sub_league"] or None,
        "position_code": r["position_code"] or None,
        "team_id": int(r["team_id"]) if r["team_id"] is not None else None,
        "team_abbrev": r["team_abbrev"],
        "rank": int(r["rank"]),
        "is_winner": bool(r["is_winner"]),
        "vote_points": float(r["vote_points"]) if r["vote_points"] is not None else None,
        "vote_share": float(r["vote_share"]) if r["vote_share"] is not None else None,
    }


_AWARD_SELECT = """
    SELECT pa.id, pa.player_id, pa.league_year_id, pa.league_level,
           pa.award_code, at2.name AS award_name, at2.category,
           pa.sub_league, pa.position_code, pa.team_id, pa.`rank`,
           pa.is_winner, pa.vote_points, pa.vote_share,
           tm.team_abbrev AS team_abbrev
    FROM player_awards pa
    JOIN award_types at2 ON at2.code = pa.award_code
    LEFT JOIN teams tm ON tm.id = pa.team_id
"""


def get_player_awards(conn, player_id: int) -> Dict[str, Any]:
    """
    All awards for one player across every season.

    Returns:
      {
        "player_id": int,
        "awards": [ <award>, ... ],     # newest season first
        "summary": { award_code: {name, wins}, ... },   # career win counts
        "total_wins": int,
      }
    """
    ensure_awards_schema(conn)
    rows = conn.execute(sa_text(_AWARD_SELECT + """
        WHERE pa.player_id = :pid
        ORDER BY pa.league_year_id DESC, at2.sort_order, pa.sub_league
    """), {"pid": int(player_id)}).mappings().all()

    awards = [_row_to_award(r) for r in rows]

    summary: Dict[str, Dict[str, Any]] = {}
    total_wins = 0
    for r in rows:
        if not r["is_winner"]:
            continue
        code = r["award_code"]
        entry = summary.setdefault(code, {"name": r["award_name"], "wins": 0})
        entry["wins"] += 1
        total_wins += 1

    return {
        "player_id": int(player_id),
        "awards": awards,
        "summary": summary,
        "total_wins": total_wins,
    }


def get_awards_for_players_bulk(conn, player_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    """Awards for many players at once (for list endpoints). Maps player_id -> [awards]."""
    if not player_ids:
        return {}
    ensure_awards_schema(conn)
    ids_csv = ",".join(str(int(p)) for p in player_ids)
    rows = conn.execute(sa_text(_AWARD_SELECT + f"""
        WHERE pa.player_id IN ({ids_csv})
        ORDER BY pa.league_year_id DESC, at2.sort_order
    """)).mappings().all()

    out: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["player_id"]), []).append(_row_to_award(r))
    return out


def get_season_awards(conn, league_year_id: int,
                      league_level: int = DEFAULT_AWARD_LEVEL) -> Dict[str, Any]:
    """
    A season's full award slate (the "results board"), grouped by award then league.
    Includes player names for display.
    """
    ensure_awards_schema(conn)
    rows = conn.execute(sa_text("""
        SELECT pa.id, pa.player_id, pa.league_year_id, pa.league_level,
               pa.award_code, at2.name AS award_name, at2.category, at2.sort_order,
               pa.sub_league, pa.position_code, pa.team_id, pa.`rank`,
               pa.is_winner, pa.vote_points, pa.vote_share,
               tm.team_abbrev AS team_abbrev,
               p.firstName, p.lastName
        FROM player_awards pa
        JOIN award_types at2 ON at2.code = pa.award_code
        JOIN simbbPlayers p ON p.id = pa.player_id
        LEFT JOIN teams tm ON tm.id = pa.team_id
        WHERE pa.league_year_id = :ly AND pa.league_level = :lvl
        ORDER BY at2.sort_order, pa.sub_league, pa.position_code, pa.`rank`
    """), {"ly": int(league_year_id), "lvl": int(league_level)}).mappings().all()

    by_award: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        code = r["award_code"]
        grp = by_award.setdefault(code, {
            "award_code": code,
            "award_name": r["award_name"],
            "category": r["category"],
            "recipients": [],
        })
        grp["recipients"].append({
            "award_id": int(r["id"]),
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}".strip(),
            "sub_league": r["sub_league"] or None,
            "position_code": r["position_code"] or None,
            "team_id": int(r["team_id"]) if r["team_id"] is not None else None,
            "team_abbrev": r["team_abbrev"],
            "rank": int(r["rank"]),
            "is_winner": bool(r["is_winner"]),
            "vote_points": float(r["vote_points"]) if r["vote_points"] is not None else None,
            "vote_share": float(r["vote_share"]) if r["vote_share"] is not None else None,
        })

    return {
        "league_year_id": int(league_year_id),
        "league_level": int(league_level),
        "awards": list(by_award.values()),
    }
