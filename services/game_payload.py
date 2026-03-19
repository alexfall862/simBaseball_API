# services/game_payload.py

from dataclasses import dataclass
from typing import Dict, Any, List

import json
import logging
import sys

from sqlalchemy import MetaData, Table, select, and_

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Roster depletion guard
# ---------------------------------------------------------------------------

class RosterDepletionError(RuntimeError):
    """
    Raised when a team's available (non-benched) player count drops below the
    minimum needed to simulate games.  Halts the sim immediately so you can
    investigate and lower the injury rate before continuing.
    """


# Minimum non-benched players / pitchers required per team to continue.
# Adjust these if you intentionally run with smaller rosters.
_MIN_AVAILABLE_PLAYERS = 12
_MIN_AVAILABLE_PITCHERS = 3


def _check_roster_availability(cache, season_week: int, subweek: str, level: int) -> None:
    """
    Pre-flight check run after the subweek cache is loaded, before any payloads
    are built or sent to the engine.

    For each team, counts players NOT benched by injury (stamina_pct == 0.0).
    If any team falls below _MIN_AVAILABLE_PLAYERS or _MIN_AVAILABLE_PITCHERS,
    prints a full report to stderr and raises RosterDepletionError.
    """
    problems = []

    for team_id, player_ids in cache.roster_by_team.items():
        available = []
        available_pitchers = []

        for pid in player_ids:
            stam_pct = cache.injury_malus.get(pid, {}).get("stamina_pct")
            benched = stam_pct is not None and float(stam_pct) == 0.0
            if benched:
                continue
            available.append(pid)
            view = cache.engine_views.get(pid) or {}
            if (view.get("ptype") or "").strip().lower() == "pitcher":
                available_pitchers.append(pid)

        team_abbrev = (cache.team_meta.get(team_id) or {}).get("team_abbrev") or str(team_id)
        total = len(player_ids)
        benched_count = total - len(available)

        if len(available) < _MIN_AVAILABLE_PLAYERS:
            problems.append(
                f"  {team_abbrev:6s} (team {team_id:>6}): "
                f"{len(available)}/{total} available — "
                f"{benched_count} benched by injury  "
                f"[need ≥{_MIN_AVAILABLE_PLAYERS} total, ≥{_MIN_AVAILABLE_PITCHERS} pitchers]"
            )
        elif len(available_pitchers) < _MIN_AVAILABLE_PITCHERS:
            problems.append(
                f"  {team_abbrev:6s} (team {team_id:>6}): "
                f"only {len(available_pitchers)} pitchers available  "
                f"[need ≥{_MIN_AVAILABLE_PITCHERS}]"
            )

    if not problems:
        return

    border = "=" * 72
    msg_lines = [
        "",
        border,
        f"  ROSTER DEPLETION — Week {season_week}, Subweek '{subweek}', Level {level}",
        border,
        "  The following teams cannot field a playable roster:",
        "",
        *problems,
        "",
        "  Simulation halted before any games were built.",
        "  To continue: lower the injury base rate in level_game_config,",
        "  or advance the week to allow injuries to heal.",
        border,
        "",
    ]
    msg = "\n".join(msg_lines)

    print(msg, file=sys.stderr, flush=True)
    logger.error("Roster depletion detected — sim halted. See stderr for details.")
    raise RosterDepletionError(msg)

from db import get_engine
from rosters import (
    _get_tables as _get_roster_tables,
    _get_player_column_categories,
    _compute_derived_raw_ratings,
)

from services.rotation import pick_starting_pitcher
from services.defense_xp import (
    compute_defensive_xp_mod_for_player,
    compute_defensive_xp_mod_for_players,
)
from services.lineups import build_defense_and_lineup
from services.pregame_injuries import roll_pregame_injuries_for_team
import random
from services.stamina import get_effective_stamina, get_effective_stamina_bulk
from services.injuries import get_active_injury_malus, get_active_injury_malus_bulk


@dataclass
class EnginePlayerView:
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return self.data

@dataclass
class EnginePlayerView:
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return self.data


# Fields to strip from play-by-play before storage.
# These are engine-internal diagnostics that have no frontend display value
# and account for ~40-60% of PBP storage size.
_PBP_STRIP_KEYS = frozenset({
    "At_Bat_Modifiers",
    "Interaction_Data",
    "Timing_Diagnostics",
    "Catch_Probability",
    "Pre_R1",
    "Pre_R2",
    "Pre_R3",
})


def _trim_play_by_play(pbp_raw):
    """Strip bulky engine-internal fields from play-by-play before storage."""
    if not isinstance(pbp_raw, list):
        return pbp_raw
    return [
        {k: v for k, v in play.items() if k not in _PBP_STRIP_KEYS}
        for play in pbp_raw
    ]


class _DummyRow:
    """
    Lightweight stand-in so _compute_derived_raw_ratings can work with a dict
    instead of a real Row object.
    """
    def __init__(self, mapping: Dict[str, Any]):
        self._mapping = mapping


def _load_position_weights(conn):
    """Load position rating weights from DB, or None to use defaults."""
    try:
        from services.rating_config import get_overall_weights, POSITION_RATING_TYPES
        all_weights = get_overall_weights(conn)
        pos = {k: v for k, v in all_weights.items() if k in POSITION_RATING_TYPES}
        return pos or None
    except Exception:
        return None


def _build_engine_player_view_from_mapping(mapping: Dict[str, Any], position_weights=None) -> Dict[str, Any]:
    """
    Core logic for turning a player row mapping (already adjusted for injuries)
    into the engine-facing dict.

    Used by both the single-player and bulk variants.
    """
    col_cats = _get_player_column_categories()
    rating_cols = col_cats["rating"]
    derived_cols = col_cats["derived"]

    # Let the existing rating logic operate on this adjusted mapping
    dummy_row = _DummyRow(mapping)
    derived = _compute_derived_raw_ratings(dummy_row, position_weights) or {}

    engine_player: Dict[str, Any] = {}

    # Core identity/metadata fields
    for key in [
        "id",
        "firstname",
        "lastname",
        "ptype",
        "durability",
        "injury_risk",
        "left_split",
        "center_split",
        "right_split",
        "bat_hand",
        "pitch_hand",
        "arm_angle",
        "pitch1_name",
        "pitch2_name",
        "pitch3_name",
        "pitch4_name",
        "pitch5_name",
    ]:
        engine_player[key] = mapping.get(key)

    # All *_base, via rating_cols
    for col in rating_cols:
        engine_player[col] = mapping.get(col)

    # Derived *_rating + pitchN_ovr
    for key, value in derived.items():
        if key in derived_cols or (key.startswith("pitch") and key.endswith("_ovr")):
            engine_player[key] = value

    return engine_player


def _get_pitch_hand_for_player(conn, player_id: int) -> str | None:
    """
    Look up simbbPlayers.pitch_hand for this player and normalize to 'L'/'R'.

    Returns:
      'L', 'R', or None if we can't tell.
    """
    tables = _get_roster_tables()
    players = tables["players"]

    row = conn.execute(
        select(players.c.pitch_hand).where(players.c.id == player_id)
    ).first()

    if not row:
        return None

    raw = row[0]
    if raw is None:
        return None

    s = str(raw).strip().upper()
    if not s:
        return None

    # Treat anything starting with L as left-handed, anything with R as right-handed.
    if s[0] == "L":
        return "L"
    if s[0] == "R":
        return "R"

    return None


def _get_pitch_hands_bulk(conn, player_ids: List[int]) -> Dict[int, str | None]:
    """
    Bulk-load pitch_hand for multiple players at once.

    Returns:
        {player_id: 'L'|'R'|None, ...}

    This replaces N individual queries with a single IN() query.
    """
    if not player_ids:
        return {}

    tables = _get_roster_tables()
    players = tables["players"]

    rows = conn.execute(
        select(players.c.id, players.c.pitch_hand).where(
            players.c.id.in_(player_ids)
        )
    ).all()

    result: Dict[int, str | None] = {}

    for row in rows:
        pid = int(row[0])
        raw = row[1]

        if raw is None:
            result[pid] = None
            continue

        s = str(raw).strip().upper()
        if not s:
            result[pid] = None
            continue

        # Treat anything starting with L as left-handed, anything with R as right-handed.
        if s[0] == "L":
            result[pid] = "L"
        elif s[0] == "R":
            result[pid] = "R"
        else:
            result[pid] = None

    # Fill in missing players with None
    for pid in player_ids:
        if pid not in result:
            result[pid] = None

    return result





_CORE_METADATA = None
_CORE_TABLES = None
_LEVEL_RULES_CACHE: Dict[int, Dict[str, Any]] = {}


def clear_game_payload_caches() -> Dict[str, bool]:
    """
    Clear all in-memory caches in the game_payload module.

    This should be called after database updates to configuration tables
    (level_catch_rates, level_rules, level_*_config, injury_types, etc.)
    to ensure fresh data is loaded on the next request.

    Returns:
        Dict with cache names and whether they were cleared (had data).
    """
    global _CORE_METADATA, _CORE_TABLES, _LEVEL_RULES_CACHE
    global _GAME_CONSTANTS_CACHE, _LEVEL_CONFIG_CACHE, _INJURY_TYPES_CACHE

    cleared = {}

    # Core tables cache
    cleared["core_tables"] = _CORE_TABLES is not None
    _CORE_METADATA = None
    _CORE_TABLES = None

    # Level rules cache
    cleared["level_rules"] = len(_LEVEL_RULES_CACHE) > 0
    _LEVEL_RULES_CACHE = {}

    # Game constants cache (static reference tables)
    cleared["game_constants"] = _GAME_CONSTANTS_CACHE is not None
    _GAME_CONSTANTS_CACHE = None

    # Level config cache (includes catch_rates, batting config, etc.)
    cleared["level_config"] = len(_LEVEL_CONFIG_CACHE) > 0
    _LEVEL_CONFIG_CACHE = {}

    # Injury types cache
    cleared["injury_types"] = _INJURY_TYPES_CACHE is not None
    _INJURY_TYPES_CACHE = None

    logger.info(f"Cleared game_payload caches: {cleared}")
    return cleared

def _get_core_tables():
    """
    Reflect and cache core tables used by game payload building and
    strategy/loading.
    """
    global _CORE_TABLES, _CORE_METADATA
    if _CORE_TABLES is not None:
        return _CORE_TABLES

    engine = get_engine()
    md = MetaData()

    # Core game tables
    gamelist = Table("gamelist", md, autoload_with=engine)
    seasons = Table("seasons", md, autoload_with=engine)
    league_years = Table("league_years", md, autoload_with=engine)
    level_rules = Table("level_rules", md, autoload_with=engine)
    level_sim_config = Table("level_sim_config", md, autoload_with=engine)
    teams = Table("teams", md, autoload_with=engine)
    player_strategies = Table("playerStrategies", md, autoload_with=engine)
    injury_types = Table("injury_types", md, autoload_with=engine)

    # Normalized simulation config - static reference tables
    field_zones = Table("field_zones", md, autoload_with=engine)
    distance_zones = Table("distance_zones", md, autoload_with=engine)
    contact_types = Table("contact_types", md, autoload_with=engine)
    fielding_outcomes = Table("fielding_outcomes", md, autoload_with=engine)
    defensive_positions = Table("defensive_positions", md, autoload_with=engine)
    fielding_difficulty_levels = Table("fielding_difficulty_levels", md, autoload_with=engine)
    catch_situations = Table("catch_situations", md, autoload_with=engine)

    # Normalized simulation config - static mapping tables
    defensive_alignment = Table("defensive_alignment", md, autoload_with=engine)
    fielding_difficulty_mapping = Table("fielding_difficulty_mapping", md, autoload_with=engine)
    time_to_ground = Table("time_to_ground", md, autoload_with=engine)
    fielding_modifier = Table("fielding_modifier", md, autoload_with=engine)

    # Normalized simulation config - level-specific tables
    level_contact_odds = Table("level_contact_odds", md, autoload_with=engine)
    level_batting_config = Table("level_batting_config", md, autoload_with=engine)
    level_game_config = Table("level_game_config", md, autoload_with=engine)
    level_distance_weights = Table("level_distance_weights", md, autoload_with=engine)
    level_fielding_weights = Table("level_fielding_weights", md, autoload_with=engine)
    level_catch_rates = Table("level_catch_rates", md, autoload_with=engine)

    # Gameplanning tables
    team_strategy = Table("team_strategy", md, autoload_with=engine)
    team_bullpen_order = Table("team_bullpen_order", md, autoload_with=engine)

    _CORE_METADATA = md
    _CORE_TABLES = {
        "gamelist": gamelist,
        "seasons": seasons,
        "league_years": league_years,
        "level_rules": level_rules,
        "level_sim_config": level_sim_config,
        "teams": teams,
        "playerStrategies": player_strategies,
        "injury_types": injury_types,
        # Static reference tables
        "field_zones": field_zones,
        "distance_zones": distance_zones,
        "contact_types": contact_types,
        "fielding_outcomes": fielding_outcomes,
        "defensive_positions": defensive_positions,
        "fielding_difficulty_levels": fielding_difficulty_levels,
        "catch_situations": catch_situations,
        # Static mapping tables
        "defensive_alignment": defensive_alignment,
        "fielding_difficulty_mapping": fielding_difficulty_mapping,
        "time_to_ground": time_to_ground,
        "fielding_modifier": fielding_modifier,
        # Level-specific tables
        "level_contact_odds": level_contact_odds,
        "level_batting_config": level_batting_config,
        "level_game_config": level_game_config,
        "level_distance_weights": level_distance_weights,
        "level_fielding_weights": level_fielding_weights,
        "level_catch_rates": level_catch_rates,
        # Gameplanning tables
        "team_strategy": team_strategy,
        "team_bullpen_order": team_bullpen_order,
    }
    return _CORE_TABLES


def _normalize_json(val):
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    try:
        return json.loads(val)
    except Exception:
        return {}


# -------------------------------------------------------------------
# League / rules / sim_config / ballpark helpers
# -------------------------------------------------------------------

from sqlalchemy import select

from typing import Dict, Any

def _get_level_rules_for_league(conn, league_level_id: int) -> Dict[str, Any]:
    """
    Load game rules for this league_level from level_rules, with simple in-process memoization.
    """
    if league_level_id in _LEVEL_RULES_CACHE:
        return _LEVEL_RULES_CACHE[league_level_id]

    tables = _get_core_tables()
    level_rules = tables["level_rules"]

    row = conn.execute(
        select(
            level_rules.c.innings,
            level_rules.c.outs_per_inning,
            level_rules.c.balls_for_walk,
            level_rules.c.strikes_for_k,
            level_rules.c.dh_bool,
        ).where(level_rules.c.league_level == league_level_id)
    ).mappings().first()

    if not row:
        raise ValueError(f"level_rules not found for league_level={league_level_id}")

    rules = {
        "innings": int(row["innings"]),
        "outs_per_inning": int(row["outs_per_inning"]),
        "balls_for_walk": int(row["balls_for_walk"]),
        "strikes_for_k": int(row["strikes_for_k"]),
        "dh": bool(row["dh_bool"]),
    }

    _LEVEL_RULES_CACHE[league_level_id] = rules
    return rules


def _resolve_league_year_id_for_game(conn, game_row) -> int:
    """
    Resolve league_years.id for this game.

    Primary path:
      gamelist.season -> seasons.id -> seasons.year -> league_years.league_year

    Fallback:
      If there is no matching league_years row for that year, fall back to
      the earliest league_years row (which, in your current DB, is 2026).
    """
    tables = _get_core_tables()
    seasons = tables["seasons"]
    league_years = tables["league_years"]

    season_id = int(game_row["season"])

    # Try to resolve via seasons.year
    s_row = conn.execute(
        select(seasons.c.year).where(seasons.c.id == season_id)
    ).first()

    if s_row:
        year = int(s_row[0])
        ly_row = conn.execute(
            select(league_years.c.id)
            .where(league_years.c.league_year == year)
            .limit(1)
        ).first()
        if ly_row:
            return int(ly_row[0])

    # Fallback: use the earliest league_years row (works fine while you only have one).
    fallback_row = conn.execute(
        select(league_years.c.id)
        .order_by(league_years.c.league_year.asc())
        .limit(1)
    ).first()

    if not fallback_row:
        raise ValueError(
            "No league_years rows present; cannot resolve league_year_id for game."
        )

    return int(fallback_row[0])


def get_level_rules(conn, league_level_id: int) -> Dict[str, Any]:
    """
    Return a simple dict of rules (innings, outs, balls, strikes) for this level.
    """
    tables = _get_core_tables()
    level_rules = tables["level_rules"]

    row = conn.execute(
        select(level_rules).where(level_rules.c.league_level == league_level_id).limit(1)
    ).mappings().first()
    if not row:
        return {
            "innings": 9,
            "outs_per_inning": 3,
            "balls_for_walk": 4,
            "strikes_for_k": 3,
        }

    m = row
    return {
        "innings": int(m["innings"]),
        "outs_per_inning": int(m["outs_per_inning"]),
        "balls_for_walk": int(m["balls_for_walk"]),
        "strikes_for_k": int(m["strikes_for_k"]),
    }


def get_level_sim_config(conn, league_level_id: int) -> Dict[str, Any]:
    """
    Return engine baseline config (baseline_outcomes_json) for this level.
    """
    tables = _get_core_tables()
    cfg_table = tables["level_sim_config"]

    row = conn.execute(
        select(cfg_table.c.baseline_outcomes_json)
        .where(cfg_table.c.league_level == league_level_id)
        .limit(1)
    ).first()

    if not row:
        return {}

    return _normalize_json(row[0])


def get_level_sim_configs_bulk(conn, league_level_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Bulk-load baseline_outcomes_json for multiple league levels.

    Returns:
        {league_level_id: {baseline_outcomes...}, ...}
    """
    if not league_level_ids:
        return {}

    tables = _get_core_tables()
    cfg_table = tables["level_sim_config"]

    rows = conn.execute(
        select(cfg_table.c.league_level, cfg_table.c.baseline_outcomes_json)
        .where(cfg_table.c.league_level.in_(league_level_ids))
    ).all()

    result: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        level_id = int(row[0])
        result[level_id] = _normalize_json(row[1])

    # Fill in missing levels with empty dict
    for level_id in league_level_ids:
        if level_id not in result:
            result[level_id] = {}

    return result


def get_ballpark_info(conn, team_id: int) -> Dict[str, Any]:
    """
    Return ballpark modifiers and name for the home team.
    """
    tables = _get_core_tables()
    teams = tables["teams"]

    row = conn.execute(
        select(
            teams.c.ballpark_name,
            getattr(teams.c, "pitch_break_mod", None),
            getattr(teams.c, "power_mod", None),
        )
        .where(teams.c.id == team_id)
        .limit(1)
    ).first()

    if not row:
        return {
            "ballpark_name": None,
            "pitch_break_mod": 1.0,
            "power_mod": 1.0,
        }

    ballpark_name, pb, pw = row
    return {
        "ballpark_name": ballpark_name,
        "pitch_break_mod": float(pb or 1.0),
        "power_mod": float(pw or 1.0),
    }


# Cache for injury types (loaded once per process)
_INJURY_TYPES_CACHE: List[Dict[str, Any]] | None = None


def get_all_injury_types(conn) -> List[Dict[str, Any]]:
    """
    Load all injury type definitions from the injury_types table.

    Results are cached since injury types don't change during runtime.

    Returns:
        List of injury type dicts with id, code, name, and other fields.
    """
    global _INJURY_TYPES_CACHE

    if _INJURY_TYPES_CACHE is not None:
        return _INJURY_TYPES_CACHE

    tables = _get_core_tables()
    injury_types = tables["injury_types"]

    rows = conn.execute(select(injury_types)).mappings().all()

    result = []
    for row in rows:
        injury_type = {}
        for key, value in row.items():
            # Normalize JSON fields
            if key.endswith("_json") and value is not None:
                injury_type[key] = _normalize_json(value)
            else:
                injury_type[key] = value
        result.append(injury_type)

    _INJURY_TYPES_CACHE = result
    return result


# -------------------------------------------------------------------
# Normalized game constants (static, cached once per process)
# -------------------------------------------------------------------

_GAME_CONSTANTS_CACHE: Dict[str, Any] | None = None


def get_game_constants(conn) -> Dict[str, Any]:
    """
    Load all static game constants from normalized tables (cached).

    This data does not vary by league level and is loaded once per process.

    Returns:
        {
            "field_zones": [{"id": 1, "name": "far_left", ...}, ...],
            "distance_zones": [...],
            "contact_types": [...],
            "fielding_outcomes": [...],
            "defensive_positions": [...],
            "fielding_difficulty_levels": [...],
            "defensive_alignment": {
                "far_left": {"deep_of": ["leftfield"], ...},
                ...
            },
            "fielding_difficulty": {
                "far_left": {"deep_of": "threestepaway", ...},
                ...
            },
            "time_to_ground": {
                "barrel": {"deep_of": 2, "middle_of": 1, ...},
                ...
            },
            "fielding_modifier": {
                "air": {"infield": {"out": 2, ...}, "outfield": {...}},
                "ground": {...}
            }
        }
    """
    global _GAME_CONSTANTS_CACHE

    if _GAME_CONSTANTS_CACHE is not None:
        return _GAME_CONSTANTS_CACHE

    tables = _get_core_tables()

    # Load reference tables as lists
    field_zones_rows = conn.execute(
        select(tables["field_zones"]).order_by(tables["field_zones"].c.sort_order)
    ).mappings().all()
    field_zones = [dict(row) for row in field_zones_rows]
    field_zone_by_id = {fz["id"]: fz["name"] for fz in field_zones}

    distance_zones_rows = conn.execute(
        select(tables["distance_zones"]).order_by(tables["distance_zones"].c.sort_order)
    ).mappings().all()
    distance_zones = [dict(row) for row in distance_zones_rows]
    distance_zone_by_id = {dz["id"]: dz["name"] for dz in distance_zones}

    contact_types_rows = conn.execute(
        select(tables["contact_types"]).order_by(tables["contact_types"].c.sort_order)
    ).mappings().all()
    contact_types = [dict(row) for row in contact_types_rows]
    contact_type_by_id = {ct["id"]: ct["name"] for ct in contact_types}

    fielding_outcomes_rows = conn.execute(
        select(tables["fielding_outcomes"]).order_by(tables["fielding_outcomes"].c.sort_order)
    ).mappings().all()
    fielding_outcomes = [dict(row) for row in fielding_outcomes_rows]
    fielding_outcome_by_id = {fo["id"]: fo["name"] for fo in fielding_outcomes}

    defensive_positions_rows = conn.execute(
        select(tables["defensive_positions"]).order_by(tables["defensive_positions"].c.sort_order)
    ).mappings().all()
    defensive_positions = [dict(row) for row in defensive_positions_rows]
    defensive_position_by_id = {dp["id"]: dp["name"] for dp in defensive_positions}

    fielding_difficulty_levels_rows = conn.execute(
        select(tables["fielding_difficulty_levels"]).order_by(tables["fielding_difficulty_levels"].c.sort_order)
    ).mappings().all()
    fielding_difficulty_levels = [dict(row) for row in fielding_difficulty_levels_rows]
    difficulty_level_by_id = {dl["id"]: dl["name"] for dl in fielding_difficulty_levels}

    # Load defensive_alignment as nested dict: {field_zone: {distance_zone: [positions by priority]}}
    alignment_rows = conn.execute(
        select(tables["defensive_alignment"]).order_by(
            tables["defensive_alignment"].c.field_zone_id,
            tables["defensive_alignment"].c.distance_zone_id,
            tables["defensive_alignment"].c.priority
        )
    ).mappings().all()

    defensive_alignment: Dict[str, Dict[str, List[str]]] = {}
    for row in alignment_rows:
        fz_name = field_zone_by_id.get(row["field_zone_id"], "unknown")
        dz_name = distance_zone_by_id.get(row["distance_zone_id"], "unknown")
        pos_name = defensive_position_by_id.get(row["position_id"], "unknown")

        if fz_name not in defensive_alignment:
            defensive_alignment[fz_name] = {}
        if dz_name not in defensive_alignment[fz_name]:
            defensive_alignment[fz_name][dz_name] = []
        defensive_alignment[fz_name][dz_name].append(pos_name)

    # Load fielding_difficulty_mapping as nested dict: {field_zone: {distance_zone: difficulty_name}}
    difficulty_rows = conn.execute(
        select(tables["fielding_difficulty_mapping"])
    ).mappings().all()

    fielding_difficulty: Dict[str, Dict[str, str]] = {}
    for row in difficulty_rows:
        fz_name = field_zone_by_id.get(row["field_zone_id"], "unknown")
        dz_name = distance_zone_by_id.get(row["distance_zone_id"], "unknown")
        diff_name = difficulty_level_by_id.get(row["difficulty_level_id"], "unknown")

        if fz_name not in fielding_difficulty:
            fielding_difficulty[fz_name] = {}
        fielding_difficulty[fz_name][dz_name] = diff_name

    # Load time_to_ground as nested dict: {contact_type: {distance_zone: time_value}}
    ttg_rows = conn.execute(
        select(tables["time_to_ground"])
    ).mappings().all()

    time_to_ground: Dict[str, Dict[str, int]] = {}
    for row in ttg_rows:
        ct_name = contact_type_by_id.get(row["contact_type_id"], "unknown")
        dz_name = distance_zone_by_id.get(row["distance_zone_id"], "unknown")
        time_val = int(row["time_value"])

        if ct_name not in time_to_ground:
            time_to_ground[ct_name] = {}
        time_to_ground[ct_name][dz_name] = time_val

    # Load fielding_modifier as nested dict: {ball_type: {zone_type: {outcome: modifier}}}
    fm_rows = conn.execute(
        select(tables["fielding_modifier"])
    ).mappings().all()

    fielding_modifier: Dict[str, Dict[str, Dict[str, int]]] = {}
    for row in fm_rows:
        ball_type = row["ball_type"]
        zone_type = row["zone_type"]
        outcome_name = fielding_outcome_by_id.get(row["fielding_outcome_id"], "unknown")
        modifier_val = int(row["modifier_value"])

        if ball_type not in fielding_modifier:
            fielding_modifier[ball_type] = {}
        if zone_type not in fielding_modifier[ball_type]:
            fielding_modifier[ball_type][zone_type] = {}
        fielding_modifier[ball_type][zone_type][outcome_name] = modifier_val

    _GAME_CONSTANTS_CACHE = {
        "field_zones": field_zones,
        "distance_zones": distance_zones,
        "contact_types": contact_types,
        "fielding_outcomes": fielding_outcomes,
        "defensive_positions": defensive_positions,
        "fielding_difficulty_levels": fielding_difficulty_levels,
        "defensive_alignment": defensive_alignment,
        "fielding_difficulty": fielding_difficulty,
        "time_to_ground": time_to_ground,
        "fielding_modifier": fielding_modifier,
    }

    return _GAME_CONSTANTS_CACHE


# -------------------------------------------------------------------
# Level-specific configuration (normalized tables)
# -------------------------------------------------------------------

_LEVEL_CONFIG_CACHE: Dict[int, Dict[str, Any]] = {}


def get_level_config_normalized(conn, league_level: int) -> Dict[str, Any]:
    """
    Load all level-specific configuration from normalized tables.

    Returns:
        {
            "batting": {
                "inside_swing": 0.65,
                "outside_swing": 0.30,
                "inside_contact": 0.87,
                "outside_contact": 0.66,
                "modexp": 2.0
            },
            "game": {
                "error_rate": 0.05,
                "steal_success": 0.65,
                "pickoff_success": 0.10,
                "pregame_injury_base_rate": 0.10,
                "ingame_injury_base_rate": 0.10,
                "energy_tick_cap": 1.5,
                "energy_step": 2.0,
                "short_leash": 0.8,
                "normal_leash": 0.7,
                "long_leash": 0.5,
                "fielding_multiplier": 0.0
            },
            "contact_odds": {
                "barrel": 7.0,
                "solid": 12.0,
                ...
            },
            "distance_weights": {
                "barrel": {"homerun": 0.20, "deep_of": 0.45, ...},
                ...
            },
            "fielding_weights": {
                "barrel": {"out": 0.25, "single": 0.28, ...},
                ...
            },
            "catch_rates": {
                "barrel": {"deep_gap": 0.30, "gap": 0.50, "routine_of": 0.92, ...},
                ...
            }
        }
    """
    if league_level in _LEVEL_CONFIG_CACHE:
        return _LEVEL_CONFIG_CACHE[league_level]

    tables = _get_core_tables()

    # Load contact type and fielding outcome name lookups
    contact_types_rows = conn.execute(
        select(tables["contact_types"].c.id, tables["contact_types"].c.name)
    ).all()
    contact_type_by_id = {row[0]: row[1] for row in contact_types_rows}

    distance_zones_rows = conn.execute(
        select(tables["distance_zones"].c.id, tables["distance_zones"].c.name)
    ).all()
    distance_zone_by_id = {row[0]: row[1] for row in distance_zones_rows}

    fielding_outcomes_rows = conn.execute(
        select(tables["fielding_outcomes"].c.id, tables["fielding_outcomes"].c.name)
    ).all()
    fielding_outcome_by_id = {row[0]: row[1] for row in fielding_outcomes_rows}

    catch_situations_rows = conn.execute(
        select(tables["catch_situations"].c.id, tables["catch_situations"].c.name)
    ).all()
    catch_situation_by_id = {row[0]: row[1] for row in catch_situations_rows}

    # Load batting config
    batting_row = conn.execute(
        select(tables["level_batting_config"])
        .where(tables["level_batting_config"].c.league_level == league_level)
    ).mappings().first()

    batting = {
        "inside_swing": float(batting_row["inside_swing"]) if batting_row else 0.65,
        "outside_swing": float(batting_row["outside_swing"]) if batting_row else 0.30,
        "inside_contact": float(batting_row["inside_contact"]) if batting_row else 0.87,
        "outside_contact": float(batting_row["outside_contact"]) if batting_row else 0.66,
        "modexp": float(batting_row["modexp"]) if batting_row else 2.0,
    }

    # Load game config
    game_row = conn.execute(
        select(tables["level_game_config"])
        .where(tables["level_game_config"].c.league_level == league_level)
    ).mappings().first()

    game = {
        "error_rate": float(game_row["error_rate"]) if game_row else 0.05,
        "steal_success": float(game_row["steal_success"]) if game_row else 0.65,
        "pickoff_success": float(game_row["pickoff_success"]) if game_row else 0.10,
        "pregame_injury_base_rate": float(game_row["pregame_injury_base_rate"]) if game_row else 0.10,
        "ingame_injury_base_rate": float(game_row["ingame_injury_base_rate"]) if game_row else 0.10,
        "energy_tick_cap": float(game_row["energy_tick_cap"]) if game_row else 1.5,
        "energy_step": float(game_row["energy_step"]) if game_row else 2.0,
        "short_leash": float(game_row["short_leash"]) if game_row else 0.8,
        "normal_leash": float(game_row["normal_leash"]) if game_row else 0.7,
        "long_leash": float(game_row["long_leash"]) if game_row else 0.5,
        "fielding_multiplier": float(game_row["fielding_multiplier"]) if game_row else 0.0,
    }

    # Load contact odds
    odds_rows = conn.execute(
        select(tables["level_contact_odds"])
        .where(tables["level_contact_odds"].c.league_level == league_level)
    ).mappings().all()

    contact_odds: Dict[str, float] = {}
    for row in odds_rows:
        ct_name = contact_type_by_id.get(row["contact_type_id"], "unknown")
        contact_odds[ct_name] = float(row["odds"])

    # Load distance weights
    dist_rows = conn.execute(
        select(tables["level_distance_weights"])
        .where(tables["level_distance_weights"].c.league_level == league_level)
    ).mappings().all()

    distance_weights: Dict[str, Dict[str, float]] = {}
    for row in dist_rows:
        ct_name = contact_type_by_id.get(row["contact_type_id"], "unknown")
        dz_name = distance_zone_by_id.get(row["distance_zone_id"], "unknown")
        weight = float(row["weight"])

        if ct_name not in distance_weights:
            distance_weights[ct_name] = {}
        distance_weights[ct_name][dz_name] = weight

    # Load fielding weights
    field_rows = conn.execute(
        select(tables["level_fielding_weights"])
        .where(tables["level_fielding_weights"].c.league_level == league_level)
    ).mappings().all()

    fielding_weights: Dict[str, Dict[str, float]] = {}
    for row in field_rows:
        ct_name = contact_type_by_id.get(row["contact_type_id"], "unknown")
        fo_name = fielding_outcome_by_id.get(row["fielding_outcome_id"], "unknown")
        weight = float(row["weight"])

        if ct_name not in fielding_weights:
            fielding_weights[ct_name] = {}
        fielding_weights[ct_name][fo_name] = weight

    # Load catch rates (situation-based OUT probabilities)
    catch_rows = conn.execute(
        select(tables["level_catch_rates"])
        .where(tables["level_catch_rates"].c.league_level == league_level)
    ).mappings().all()

    catch_rates: Dict[str, Dict[str, float]] = {}
    for row in catch_rows:
        ct_name = contact_type_by_id.get(row["contact_type_id"], "unknown")
        cs_name = catch_situation_by_id.get(row["catch_situation_id"], "unknown")
        rate = float(row["catch_rate"])

        if ct_name not in catch_rates:
            catch_rates[ct_name] = {}
        catch_rates[ct_name][cs_name] = rate

    result = {
        "batting": batting,
        "game": game,
        "contact_odds": contact_odds,
        "distance_weights": distance_weights,
        "fielding_weights": fielding_weights,
        "catch_rates": catch_rates,
    }

    _LEVEL_CONFIG_CACHE[league_level] = result
    return result


def get_level_configs_normalized_bulk(conn, league_levels: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Bulk-load level configurations for multiple league levels.

    Returns:
        {league_level: level_config_dict, ...}
    """
    if not league_levels:
        return {}

    result: Dict[int, Dict[str, Any]] = {}
    for level in league_levels:
        result[level] = get_level_config_normalized(conn, level)

    return result


# -------------------------------------------------------------------
# Roster + strategy helpers
# -------------------------------------------------------------------

def _get_team_roster_player_ids(conn, team_id: int) -> List[int]:
    """
    Return a list of player IDs on the specified team_id's active roster.

    Mirrors the join pattern in rosters._build_ratings_base_stmt, but
    filtered directly by teams.id.
    """
    r_tables = _get_roster_tables()
    contracts = r_tables["contracts"]
    details = r_tables["contract_details"]
    shares = r_tables["contract_team_share"]
    orgs = r_tables["organizations"]
    players = r_tables["players"]
    levels = r_tables["levels"]
    teams = r_tables["teams"]

    conditions = [
        contracts.c.isActive == 1,
        shares.c.isHolder == 1,
        teams.c.id == team_id,
    ]

    stmt = (
        select(players.c.id)
        .select_from(
            shares
            .join(details, shares.c.contractDetailsID == details.c.id)
            .join(contracts, details.c.contractID == contracts.c.id)
            .join(orgs, orgs.c.id == shares.c.orgID)
            .join(players, players.c.id == contracts.c.playerID)
            .join(levels, levels.c.id == contracts.c.current_level)
            .outerjoin(
                teams,
                and_(
                    teams.c.orgID == orgs.c.id,
                    teams.c.team_level == contracts.c.current_level,
                ),
            )
        )
        .where(and_(*conditions))
    )

    rows = conn.execute(stmt).scalars().all()
    return [int(pid) for pid in rows]

DEFAULT_PLAYER_STRATEGY = {
    "plate_approach": "normal",
    "pitching_approach": "normal",
    "baserunning_approach": "normal",
    "usage_preference": "normal",
    "stealfreq": 1.87,          # Steal attempt frequency (0-100, represents %)
    "pickofffreq": 1.0,         # Pickoff attempt frequency (0-100, represents %)
    "pitchchoices": [1, 1, 1, 1, 1],  # Pitch mix weights for 5 pitch slots
    "pitchpull": None,          # None = use team bullpen_cutoff default
    "pulltend": None,           # None = "normal"
}

def _load_player_strategies_bulk(
    conn,
    player_ids: list[int],
    org_id: int | None,
) -> Dict[int, Dict[str, Any]]:
    """
    Bulk-load strategies for many players at once from playerStrategies.

    If multiple rows exist for a player, prefer the one with matching orgID,
    falling back to org-agnostic rows.

    Returns a dict:
      {player_id: {...strategy fields...}, ...}
    with defaults for players without an explicit strategy row.
    """
    if not player_ids:
        return {}

    tables = _get_core_tables()
    strategies = tables["playerStrategies"]

    # NOTE: column names use camelCase in this schema (playerID, orgID)
    stmt = select(strategies).where(strategies.c.playerID.in_(player_ids))
    rows = list(conn.execute(stmt).mappings())

    by_player: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        pid = int(row["playerID"])
        row_org = row.get("orgID")

        # If org_id is provided, prefer rows with that orgID over others.
        if org_id is not None:
            if row_org == org_id:
                # Always prefer exact org match for this pid
                by_player[pid] = dict(row)
            else:
                # Only set if we don't already have an exact match
                if pid not in by_player:
                    by_player[pid] = dict(row)
        else:
            # No org context: just take the first row per player
            if pid not in by_player:
                by_player[pid] = dict(row)

    out: Dict[int, Dict[str, Any]] = {}

    for pid in player_ids:
        row = by_player.get(pid)
        if not row:
            out[pid] = DEFAULT_PLAYER_STRATEGY.copy()
            continue

        # String fields: use 'or' pattern (empty string -> default)
        strat = {
            "plate_approach": row.get("plate_approach") or DEFAULT_PLAYER_STRATEGY["plate_approach"],
            "pitching_approach": row.get("pitching_approach") or DEFAULT_PLAYER_STRATEGY["pitching_approach"],
            "baserunning_approach": row.get("baserunning_approach") or DEFAULT_PLAYER_STRATEGY["baserunning_approach"],
            "usage_preference": row.get("usage_preference") or DEFAULT_PLAYER_STRATEGY["usage_preference"],
        }

        # Numeric fields: explicit None check (0 is a valid value)
        stealfreq = row.get("stealfreq")
        strat["stealfreq"] = float(stealfreq) if stealfreq is not None else DEFAULT_PLAYER_STRATEGY["stealfreq"]

        pickofffreq = row.get("pickofffreq")
        strat["pickofffreq"] = float(pickofffreq) if pickofffreq is not None else DEFAULT_PLAYER_STRATEGY["pickofffreq"]

        # Array field: handle JSON string or list
        pitchchoices_raw = row.get("pitchchoices")
        if pitchchoices_raw is None:
            strat["pitchchoices"] = DEFAULT_PLAYER_STRATEGY["pitchchoices"].copy()
        elif isinstance(pitchchoices_raw, list):
            strat["pitchchoices"] = pitchchoices_raw
        else:
            # Try to parse as JSON string
            try:
                strat["pitchchoices"] = json.loads(pitchchoices_raw)
            except (TypeError, json.JSONDecodeError):
                strat["pitchchoices"] = DEFAULT_PLAYER_STRATEGY["pitchchoices"].copy()

        # Pitcher leash settings (None = use team defaults)
        pitchpull = row.get("pitchpull")
        strat["pitchpull"] = int(pitchpull) if pitchpull is not None else None

        pulltend = row.get("pulltend")
        strat["pulltend"] = pulltend if pulltend else None

        out[pid] = strat

    return out

def _load_player_strategy(conn, player_id: int, org_id: int | None = None) -> Dict[str, Any]:
    """
    Load per-player strategy for the given player/org, if present.
    Defaults all strategy fields if not set.
    """
    tables = _get_core_tables()
    strategies = tables["playerStrategies"]

    conditions = [strategies.c.playerID == player_id]
    if org_id is not None and hasattr(strategies.c, "orgID"):
        conditions.append(strategies.c.orgID == org_id)

    stmt = select(strategies).where(and_(*conditions)).limit(1)
    row = conn.execute(stmt).mappings().first()

    if not row:
        return DEFAULT_PLAYER_STRATEGY.copy()

    # String fields
    strat = {
        "plate_approach": row.get("plate_approach") or DEFAULT_PLAYER_STRATEGY["plate_approach"],
        "pitching_approach": row.get("pitching_approach") or DEFAULT_PLAYER_STRATEGY["pitching_approach"],
        "baserunning_approach": row.get("baserunning_approach") or DEFAULT_PLAYER_STRATEGY["baserunning_approach"],
        "usage_preference": row.get("usage_preference") or DEFAULT_PLAYER_STRATEGY["usage_preference"],
    }

    # Numeric fields: explicit None check (0 is valid)
    stealfreq = row.get("stealfreq")
    strat["stealfreq"] = float(stealfreq) if stealfreq is not None else DEFAULT_PLAYER_STRATEGY["stealfreq"]

    pickofffreq = row.get("pickofffreq")
    strat["pickofffreq"] = float(pickofffreq) if pickofffreq is not None else DEFAULT_PLAYER_STRATEGY["pickofffreq"]

    # Array field: handle JSON string or list
    pitchchoices_raw = row.get("pitchchoices")
    if pitchchoices_raw is None:
        strat["pitchchoices"] = DEFAULT_PLAYER_STRATEGY["pitchchoices"].copy()
    elif isinstance(pitchchoices_raw, list):
        strat["pitchchoices"] = pitchchoices_raw
    else:
        try:
            strat["pitchchoices"] = json.loads(pitchchoices_raw)
        except (TypeError, json.JSONDecodeError):
            strat["pitchchoices"] = DEFAULT_PLAYER_STRATEGY["pitchchoices"].copy()

    # Pitcher leash settings
    pitchpull = row.get("pitchpull")
    strat["pitchpull"] = int(pitchpull) if pitchpull is not None else None

    pulltend = row.get("pulltend")
    strat["pulltend"] = pulltend if pulltend else None

    return strat


# -------------------------------------------------------------------
# Team-level strategy + bullpen loading
# -------------------------------------------------------------------

_DEFAULT_TEAM_STRATEGY = {
    "outfield_spacing": "normal",
    "infield_spacing": "normal",
    "bullpen_cutoff": 100,
    "bullpen_priority": "rest",
    "emergency_pitcher_id": None,
    "intentional_walk_list": [],
}


def _load_team_strategy(conn, team_id: int) -> Dict[str, Any]:
    """Load team strategy from team_strategy table, or return defaults."""
    tables = _get_core_tables()
    ts = tables["team_strategy"]

    row = conn.execute(
        select(ts).where(ts.c.team_id == team_id).limit(1)
    ).mappings().first()

    if not row:
        return {**_DEFAULT_TEAM_STRATEGY, "team_id": team_id}

    d = dict(row)
    iwl = d.get("intentional_walk_list")
    if iwl is None:
        d["intentional_walk_list"] = []
    elif isinstance(iwl, str):
        try:
            d["intentional_walk_list"] = json.loads(iwl)
        except (TypeError, json.JSONDecodeError):
            d["intentional_walk_list"] = []

    return {
        "team_id": team_id,
        "outfield_spacing": d.get("outfield_spacing", "normal"),
        "infield_spacing": d.get("infield_spacing", "normal"),
        "bullpen_cutoff": int(d.get("bullpen_cutoff") or 100),
        "bullpen_priority": d.get("bullpen_priority", "rest"),
        "emergency_pitcher_id": d.get("emergency_pitcher_id"),
        "intentional_walk_list": d["intentional_walk_list"],
    }


def _load_bullpen_order(conn, team_id: int) -> List[Dict[str, Any]]:
    """Load ordered bullpen preference list from team_bullpen_order."""
    tables = _get_core_tables()
    bo = tables["team_bullpen_order"]

    rows = conn.execute(
        select(bo).where(bo.c.team_id == team_id).order_by(bo.c.slot.asc())
    ).mappings().all()

    return [{"slot": int(r["slot"]), "player_id": int(r["player_id"]), "role": r["role"]} for r in rows]


# -------------------------------------------------------------------
# Effective player view (base + injuries -> derived ratings)
# -------------------------------------------------------------------

def build_engine_player_view(conn, player_id: int) -> EnginePlayerView:
    """
    Build the engine-facing view of a single player (excluding stamina):

      - pulls the simbbPlayers row
      - applies injury maluses to all *_base attributes
      - recomputes internal *_rating and pitchN_ovr using _compute_derived_raw_ratings
      - returns a flat dict with id, names, splits, type, durability, injury_risk,
        all *_base attributes (post-maluses), and derived *_rating / pitchN_ovr.

    Does NOT include:
      - stamina (that comes from the stamina service)
      - strategy (that comes from playerStrategies)
      - 20–80 normalization (UI-only)
    """
    r_tables = _get_roster_tables()
    players = r_tables["players"]

    stmt = select(players).where(players.c.id == player_id).limit(1)
    row = conn.execute(stmt).first()
    if row is None:
        raise ValueError(f"Player {player_id} not found in simbbPlayers")

    raw_mapping = dict(row._mapping)

    # Apply injury maluses to *_base attributes (multiplicative)
    malus = get_active_injury_malus(conn, player_id)
    adjusted_mapping = dict(raw_mapping)

    for attr, factor in malus.items():
        if attr == "stamina_pct":
            continue  # handled via _injury_stamina_pct below
        base_key = f"{attr}_base"
        if base_key not in adjusted_mapping:
            continue
        try:
            base_num = float(adjusted_mapping[base_key] or 0.0)
        except (TypeError, ValueError):
            base_num = 0.0
        try:
            factor_num = float(factor)
        except (TypeError, ValueError):
            factor_num = 1.0
        adjusted_mapping[base_key] = max(1.0, base_num * factor_num)

    # Load position weights from DB
    pos_weights = _load_position_weights(conn)
    engine_player = _build_engine_player_view_from_mapping(adjusted_mapping, pos_weights)

    # Carry stamina_pct through for persisted injuries that bench a player
    if "stamina_pct" in malus:
        try:
            engine_player["_injury_stamina_pct"] = float(malus["stamina_pct"])
        except (TypeError, ValueError):
            pass

    return EnginePlayerView(engine_player)

def build_engine_player_views_bulk(
    conn,
    player_ids: List[int],
) -> Dict[int, Dict[str, Any]]:
    """
    Bulk version of build_engine_player_view, but only for the parts that
    depend on simbbPlayers + injuries.

    - Loads all simbbPlayers rows for the given player IDs in a single query.
    - For each player:
        - applies their injury malus to *_base attributes
        - recomputes derived ratings via _build_engine_player_view_from_mapping
    - Returns a dict:
        {player_id: engine_player_dict}

    NOTE: This deliberately does *not* attach stamina, strategy, or XP mods.
          Those are layered on later in build_team_game_side.
    """
    if not player_ids:
        return {}

    ids = [int(pid) for pid in player_ids]

    r_tables = _get_roster_tables()
    players = r_tables["players"]

    # 1) Load all simbbPlayers rows in one shot
    rows = (
        conn.execute(
            select(players).where(players.c.id.in_(ids))
        )
        .mappings()
        .all()
    )

    raw_by_id: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        pid = int(row["id"])
        raw_by_id[pid] = dict(row)

    results: Dict[int, Dict[str, Any]] = {}

    # 2) Bulk-load injury maluses and position weights
    malus_by_player = get_active_injury_malus_bulk(conn, ids)
    pos_weights = _load_position_weights(conn)

    for pid in ids:
        raw_mapping = raw_by_id.get(pid)
        if raw_mapping is None:
            continue

        adjusted_mapping = dict(raw_mapping)
        malus = malus_by_player.get(pid) or {}

        for attr, factor in malus.items():
            if attr == "stamina_pct":
                continue  # handled via _injury_stamina_pct below
            base_key = f"{attr}_base"
            if base_key not in adjusted_mapping:
                continue
            try:
                base_num = float(adjusted_mapping[base_key] or 0.0)
            except (TypeError, ValueError):
                base_num = 0.0
            try:
                factor_num = float(factor)
            except (TypeError, ValueError):
                factor_num = 1.0
            adjusted_mapping[base_key] = max(0.0, base_num * factor_num)

        engine_player = _build_engine_player_view_from_mapping(adjusted_mapping, pos_weights)

        # Carry stamina_pct through so it can be applied when stamina is
        # attached later (persisted injuries that should bench a player use
        # stamina_pct: 0.0 to force stamina to 0).
        if "stamina_pct" in malus:
            try:
                engine_player["_injury_stamina_pct"] = float(malus["stamina_pct"])
            except (TypeError, ValueError):
                pass

        results[pid] = engine_player

    return results

# -------------------------------------------------------------------
# Lineup + team payload
# -------------------------------------------------------------------

def _compute_offense_score(p: Dict[str, Any]) -> float:
    """
    Crude offensive score for lineup ordering.
    """
    comps = [
        p.get("contact_base"),
        p.get("power_base"),
        p.get("eye_base"),
        p.get("discipline_base"),
    ]
    vals = []
    for v in comps:
        try:
            if v is not None:
                vals.append(float(v))
        except (TypeError, ValueError):
            continue
    return sum(vals) if vals else 0.0

def _get_rating(p: Dict[str, Any], key: str) -> float:
    """
    Safe helper to read a defensive rating from the player dict.
    Missing / non-numeric values are treated as 0.
    """
    try:
        v = p.get(key)
        if v is None:
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0

POSITION_CODES = [
    "c", "fb", "sb", "tb", "ss", "lf", "cf", "rf", "dh", "p"]

def build_team_game_side(
    conn,
    team_id: int,
    league_level_id: int,
    league_year_id: int,
    season_week: int,
    starter_id: int,
    vs_hand: str | None,
    random_seed: int | None,
    use_dh: bool,
) -> Dict[str, Any]:
    """
    Build the engine-facing payload for one team in a game.

    Includes:
      - players: list of player dicts (base + derived ratings, stamina, strategy)
      - starting_pitcher_id
      - available_pitcher_ids
      - lineup: batting order (player IDs)
      - bench: all other IDs (not in lineup, not SP)
    """
    r_tables = _get_roster_tables()
    teams = r_tables["teams"]

    team_row = conn.execute(
        select(
            teams.c.orgID,
            teams.c.team_abbrev,
            teams.c.team_name,
            teams.c.team_nickname,
        ).where(teams.c.id == team_id).limit(1)
    ).first()
    if not team_row:
        raise ValueError(f"Team id {team_id} not found")

    org_id = int(team_row[0])
    team_abbrev = team_row[1]
    team_name = team_row[2]
    team_nickname = team_row[3]

    player_ids = _get_team_roster_player_ids(conn, team_id)
    players_by_id: Dict[int, Dict[str, Any]] = {}


    if not player_ids:
        # No players; return an empty shell
        return {
            "team_id": team_id,
            "team_abbrev": team_abbrev,
            "team_name": team_name,
            "team_nickname": team_nickname,
            "org_id": org_id,
            "players": [],
            "starting_pitcher_id": None,
            "available_pitcher_ids": [],
            "defense": {},
            "lineup": [],
            "bench": [],
            "pregame_injuries": [],
        }
    
    # --- Bulk-load strategies, XP, player views, and stamina once ---
    strategies_by_player = _load_player_strategies_bulk(conn, player_ids, org_id=org_id)
    xp_by_player = compute_defensive_xp_mod_for_players(conn, player_ids, league_level_id)

    # Team-level strategy + bullpen ordering
    team_strategy = _load_team_strategy(conn, team_id)
    bullpen_order = _load_bullpen_order(conn, team_id)

    # Engine-facing base views (players + injuries + derived ratings)
    engine_views_by_player = build_engine_player_views_bulk(conn, player_ids)

    # Stamina: bulk wrapper (currently loops over get_effective_stamina; we can
    # later optimize internals to do a single IN() query against fatigue tables).
    stamina_by_player = get_effective_stamina_bulk(conn, player_ids, league_year_id)

    for pid in player_ids:
        base_view = engine_views_by_player.get(pid)
        if base_view is None:
            # If something went wrong / player missing, skip or handle as needed.
            # For now, we skip; you can raise if you'd rather fail hard.
            continue

        ep = dict(base_view)

        # Stamina — apply persisted injury stamina_pct if present
        raw_stamina = int(stamina_by_player.get(pid, 100))
        injury_stam_pct = ep.pop("_injury_stamina_pct", None)
        if injury_stam_pct is not None:
            raw_stamina = int(max(0.0, raw_stamina * injury_stam_pct))
        ep["stamina"] = raw_stamina
        ep["benched_by_injury"] = (injury_stam_pct is not None and raw_stamina == 0)

        # Strategy
        strat = strategies_by_player.get(pid) or DEFAULT_PLAYER_STRATEGY
        ep.update(strat)

        # Defensive XP modifiers
        ep["defensive_xp_mod"] = xp_by_player.get(pid, {pos: 0.0 for pos in POSITION_CODES})

        players_by_id[pid] = ep
    # --- Pregame injuries (ephemeral, per-game only) ---
    pregame_injuries: List[Dict[str, Any]] = []

    if random_seed is not None:
        # Derive a deterministic team-specific seed
        team_seed = (int(random_seed) * 31 + int(team_id)) & 0xFFFFFFFF
        rng = random.Random(team_seed)

        pregame_injuries = roll_pregame_injuries_for_team(
            conn=conn,
            league_level_id=league_level_id,
            team_id=team_id,
            players_by_id=players_by_id,
            rng=rng,
        )
        if pregame_injuries:
            _persist_pregame_injuries(conn, pregame_injuries, league_year_id)

    # 2) Validate starter is on the roster and not benched; fallback to best available if not
    if starter_id not in players_by_id or players_by_id[starter_id].get("benched_by_injury"):
        roster_pitchers = [
            pid for pid, pdata in players_by_id.items()
            if (pdata.get("ptype") or "").lower() == "pitcher"
        ]
        # Prefer pitchers not benched by injury; fall back to anyone if no healthy pitchers
        eligible = [pid for pid in roster_pitchers if not players_by_id[pid].get("benched_by_injury")]
        if not eligible:
            eligible = roster_pitchers
        if eligible:
            starter_id = max(eligible, key=lambda pid: players_by_id[pid].get("stamina", 100))
            logger.warning(
                "build_team_game_side: starter_id not on roster or benched for team %s, "
                "falling back to player %s", team_id, starter_id,
            )
        else:
            logger.error(
                "build_team_game_side: no pitchers on roster for team %s", team_id,
            )

    # 3) Available pitchers: all pitchers except starter
    #    Respect bullpen ordering if configured, append any unordered pitchers after
    all_pitcher_ids = {
        pid for pid, pdata in players_by_id.items()
        if (pdata.get("ptype") or "").lower() == "pitcher" and pid != starter_id
    }
    if bullpen_order:
        ordered_ids = [bp["player_id"] for bp in bullpen_order
                       if bp["player_id"] in all_pitcher_ids]
        remaining = [pid for pid in all_pitcher_ids if pid not in set(ordered_ids)]
        available_pitcher_ids: List[int] = ordered_ids + remaining
    else:
        available_pitcher_ids: List[int] = list(all_pitcher_ids)

    # 4) Defensive alignment + batting order (depth chart aware, with fallback)
    defense, lineup_ids, bench_ids = build_defense_and_lineup(
        conn=conn,
        team_id=team_id,
        league_level_id=league_level_id,
        league_year_id=league_year_id,
        season_week=season_week,
        vs_hand=vs_hand,
        players_by_id=players_by_id,
        starter_id=starter_id,
        use_dh=use_dh,  # flip to True later for DH leagues
    )

    return {
        "team_id": team_id,
        "team_abbrev": team_abbrev,
        "team_name": team_name,
        "team_nickname": team_nickname,
        "org_id": org_id,
        "players": list(players_by_id.values()),
        "starting_pitcher_id": starter_id,
        "available_pitcher_ids": available_pitcher_ids,
        "defense": defense,
        "lineup": lineup_ids,
        "bench": bench_ids,
        "pregame_injuries": pregame_injuries,
        "team_strategy": team_strategy,
        "bullpen_order": bullpen_order,
        "vs_hand": vs_hand,
    }

# -------------------------------------------------------------------
# Cache-aware assembly (zero DB per game)
# -------------------------------------------------------------------

def build_team_game_side_from_cache(
    conn,
    cache,
    team_id: int,
    league_level_id: int,
    league_year_id: int,
    season_week: int,
    starter_id: int,
    vs_hand: str | None,
    random_seed: int | None,
    use_dh: bool,
) -> Dict[str, Any]:
    """
    Same as build_team_game_side but reads from SubweekCache.
    Only conn is needed for pregame injuries (reference data lookups).
    """
    from services.lineups import build_defense_and_lineup_from_cache
    from services.subweek_cache import resolve_strategies_for_team

    meta = cache.team_meta.get(team_id)
    if not meta:
        raise ValueError(f"Team id {team_id} not found in cache")

    org_id = cache.org_by_team.get(team_id, int(meta["orgID"]))
    team_abbrev = meta["team_abbrev"]
    team_name = meta["team_name"]
    team_nickname = meta["team_nickname"]

    player_ids = cache.roster_by_team.get(team_id, [])

    if not player_ids:
        return {
            "team_id": team_id,
            "team_abbrev": team_abbrev,
            "team_name": team_name,
            "team_nickname": team_nickname,
            "org_id": org_id,
            "players": [],
            "starting_pitcher_id": None,
            "available_pitcher_ids": [],
            "defense": {},
            "lineup": [],
            "bench": [],
            "pregame_injuries": [],
        }

    # All from cache — no DB queries
    strategies_by_player = resolve_strategies_for_team(cache, player_ids, org_id)
    team_strategy = cache.team_strategy_by_team.get(team_id, _DEFAULT_TEAM_STRATEGY.copy())
    bullpen_order = cache.bullpen_order_by_team.get(team_id, [])

    players_by_id: Dict[int, Dict[str, Any]] = {}

    for pid in player_ids:
        base_view = cache.engine_views.get(pid)
        if base_view is None:
            continue

        ep = dict(base_view)

        raw_stamina = int(cache.stamina.get(pid, 100))
        stam_pct = cache.injury_malus.get(pid, {}).get("stamina_pct")
        if stam_pct is not None:
            raw_stamina = int(max(0, raw_stamina * float(stam_pct)))
        ep["stamina"] = raw_stamina
        ep["benched_by_injury"] = (stam_pct is not None and raw_stamina == 0)

        strat = strategies_by_player.get(pid) or DEFAULT_PLAYER_STRATEGY
        ep.update(strat)

        ep["defensive_xp_mod"] = cache.xp_mods.get(
            pid, {pos: 0.0 for pos in POSITION_CODES}
        )

        players_by_id[pid] = ep

    # Pregame injuries (still uses conn for reference data — few queries, cached)
    pregame_injuries: List[Dict[str, Any]] = []
    if random_seed is not None:
        team_seed = (int(random_seed) * 31 + int(team_id)) & 0xFFFFFFFF
        rng = random.Random(team_seed)
        pregame_injuries = roll_pregame_injuries_for_team(
            conn=conn,
            league_level_id=league_level_id,
            team_id=team_id,
            players_by_id=players_by_id,
            rng=rng,
        )
        if pregame_injuries:
            _persist_pregame_injuries(conn, pregame_injuries, league_year_id)

    # Validate starter is on the roster; fallback to best available if not
    if starter_id not in players_by_id or players_by_id[starter_id].get("benched_by_injury"):
        roster_pitchers = [
            pid for pid, pdata in players_by_id.items()
            if (pdata.get("ptype") or "").lower() == "pitcher"
        ]
        # Prefer pitchers not benched by injury; fall back to anyone if no healthy pitchers
        eligible = [pid for pid in roster_pitchers if not players_by_id[pid].get("benched_by_injury")]
        if not eligible:
            eligible = roster_pitchers
        if eligible:
            starter_id = max(eligible, key=lambda pid: players_by_id[pid].get("stamina", 100))
            logger.warning(
                "build_team_game_side_from_cache: starter_id not on roster or benched for team %s, "
                "falling back to player %s", team_id, starter_id,
            )
        else:
            logger.error(
                "build_team_game_side_from_cache: no pitchers on roster for team %s", team_id,
            )

    # Available pitchers (all pitchers except starter, respect bullpen order)
    all_pitcher_ids = {
        pid for pid, pdata in players_by_id.items()
        if (pdata.get("ptype") or "").lower() == "pitcher" and pid != starter_id
    }
    if bullpen_order:
        ordered_ids = [bp["player_id"] for bp in bullpen_order
                       if bp["player_id"] in all_pitcher_ids]
        remaining = [pid for pid in all_pitcher_ids if pid not in set(ordered_ids)]
        available_pitcher_ids: List[int] = ordered_ids + remaining
    else:
        available_pitcher_ids: List[int] = list(all_pitcher_ids)

    # Defense + lineup from cache
    defense, lineup_ids, bench_ids = build_defense_and_lineup_from_cache(
        cache=cache,
        team_id=team_id,
        vs_hand=vs_hand,
        players_by_id=players_by_id,
        starter_id=starter_id,
        use_dh=use_dh,
    )

    return {
        "team_id": team_id,
        "team_abbrev": team_abbrev,
        "team_name": team_name,
        "team_nickname": team_nickname,
        "org_id": org_id,
        "players": list(players_by_id.values()),
        "starting_pitcher_id": starter_id,
        "available_pitcher_ids": available_pitcher_ids,
        "defense": defense,
        "lineup": lineup_ids,
        "bench": bench_ids,
        "pregame_injuries": pregame_injuries,
        "team_strategy": team_strategy,
        "bullpen_order": bullpen_order,
        "vs_hand": vs_hand,
    }


def build_game_payload_core_from_cache(
    conn,
    cache,
    game_row,
    league_year_id: int,
    rules_by_level: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Same as build_game_payload_core but uses SubweekCache for team data.
    Only conn is passed through for pregame injury reference data.
    """
    from services.rotation import pick_starting_pitcher_from_cache

    game_id = int(game_row["id"])
    league_level_id = int(game_row["league_level"])
    season_week = int(game_row["season_week"])
    season_subweek = game_row.get("season_subweek")

    rules = rules_by_level.get(str(league_level_id), {})
    use_dh = bool(rules.get("dh", False))

    away_team_id = int(game_row["away_team"])
    home_team_id = int(game_row["home_team"])

    # Ballpark from cache
    home_meta = cache.team_meta.get(home_team_id, {})
    ballpark = {
        "ballpark_name": home_meta.get("ballpark_name"),
        "pitch_break_mod": float(home_meta.get("pitch_break_mod") or 1.0),
        "power_mod": float(home_meta.get("power_mod") or 1.0),
    }

    random_seed = None
    if "random_seed" in game_row and game_row["random_seed"] is not None:
        random_seed = int(game_row["random_seed"])

    # Pick starters from cache (zero DB)
    away_rot = pick_starting_pitcher_from_cache(cache, away_team_id)
    home_rot = pick_starting_pitcher_from_cache(cache, home_team_id)

    away_sp_id = int(away_rot["starter_id"])
    home_sp_id = int(home_rot["starter_id"])

    # Pitch hands from cache
    away_sp_hand = cache.pitch_hands.get(away_sp_id)
    home_sp_hand = cache.pitch_hands.get(home_sp_id)

    away_vs_hand = home_sp_hand
    home_vs_hand = away_sp_hand

    # Build team sides from cache
    home_side = build_team_game_side_from_cache(
        conn=conn,
        cache=cache,
        team_id=home_team_id,
        league_level_id=league_level_id,
        league_year_id=league_year_id,
        season_week=season_week,
        starter_id=home_sp_id,
        vs_hand=home_vs_hand,
        random_seed=random_seed,
        use_dh=use_dh,
    )
    away_side = build_team_game_side_from_cache(
        conn=conn,
        cache=cache,
        team_id=away_team_id,
        league_level_id=league_level_id,
        league_year_id=league_year_id,
        season_week=season_week,
        starter_id=away_sp_id,
        vs_hand=away_vs_hand,
        random_seed=random_seed,
        use_dh=use_dh,
    )

    # Carry scheduled rotation slot so advancement knows which slot to move past
    home_side["scheduled_rotation_slot"] = home_rot.get("scheduled_rotation_slot")
    away_side["scheduled_rotation_slot"] = away_rot.get("scheduled_rotation_slot")

    payload: Dict[str, Any] = {
        "game_id": game_id,
        "league_level_id": league_level_id,
        "league_year_id": league_year_id,
        "season_week": season_week,
        "season_subweek": season_subweek,
        "ballpark": ballpark,
        "home_side": home_side,
        "away_side": away_side,
    }

    if random_seed is not None:
        payload["random_seed"] = str(random_seed)

    return payload


# -------------------------------------------------------------------
# Public: full game payload
# -------------------------------------------------------------------

def build_game_payload_core(conn, game_id: int) -> Dict[str, Any]:
    """
    Build the core game-specific payload for a single game_id.

    This contains only the game-specific data (teams, ballpark, etc.)
    without the metadata that should live at root level (game_constants,
    level_config, injury_types, rules).

    Used internally by both build_game_payload() and build_week_payloads().

    Returns:
        {
            "game_id": 123,
            "league_level_id": 9,
            "league_year_id": 1,
            "season_week": 1,
            "season_subweek": "a",
            "ballpark": {...},
            "home_side": {...},
            "away_side": {...},
            "random_seed": "12345"  # optional
        }
    """
    tables = _get_core_tables()
    gamelist = tables["gamelist"]

    game_row = conn.execute(
        select(gamelist).where(gamelist.c.id == game_id)
    ).mappings().first()

    if not game_row:
        raise ValueError(f"Game id {game_id} not found in gamelist")

    league_level_id = int(game_row["league_level"])
    league_year_id = _resolve_league_year_id_for_game(conn, game_row)

    # Load game rules for this league level (needed for DH flag)
    rules = _get_level_rules_for_league(conn, league_level_id)
    use_dh = bool(rules["dh"])

    away_team_id = int(game_row["away_team"])
    home_team_id = int(game_row["home_team"])
    season_week = int(game_row["season_week"])
    season_subweek = game_row.get("season_subweek")

    # Load ballpark modifiers for home team's stadium
    ballpark = get_ballpark_info(conn, home_team_id)

    # random_seed may or may not exist yet depending on your schema
    random_seed = None
    if "random_seed" in game_row and game_row["random_seed"] is not None:
        random_seed = int(game_row["random_seed"])

    # --- Pick starting pitchers for both teams ---
    away_rot = pick_starting_pitcher(conn, away_team_id, league_year_id)
    home_rot = pick_starting_pitcher(conn, home_team_id, league_year_id)

    away_sp_id = int(away_rot["starter_id"])
    home_sp_id = int(home_rot["starter_id"])

    # --- Get opponent SP handedness for vs_hand platoon logic ---
    # Bulk-load pitch hands for both starting pitchers at once
    pitch_hands = _get_pitch_hands_bulk(conn, [away_sp_id, home_sp_id])
    away_sp_hand = pitch_hands.get(away_sp_id)
    home_sp_hand = pitch_hands.get(home_sp_id)

    # Each lineup sees the *opponent* SP hand
    away_vs_hand = home_sp_hand
    home_vs_hand = away_sp_hand

    # --- Build team payloads ---
    home_side = build_team_game_side(
        conn=conn,
        team_id=home_team_id,
        league_level_id=league_level_id,
        league_year_id=league_year_id,
        season_week=season_week,
        starter_id=home_sp_id,
        vs_hand=home_vs_hand,
        random_seed=random_seed,
        use_dh=use_dh,
    )
    away_side = build_team_game_side(
        conn=conn,
        team_id=away_team_id,
        league_level_id=league_level_id,
        league_year_id=league_year_id,
        season_week=season_week,
        starter_id=away_sp_id,
        vs_hand=away_vs_hand,
        random_seed=random_seed,
        use_dh=use_dh,
    )

    # Carry scheduled rotation slot so advancement knows which slot to move past
    home_side["scheduled_rotation_slot"] = home_rot.get("scheduled_rotation_slot")
    away_side["scheduled_rotation_slot"] = away_rot.get("scheduled_rotation_slot")

    payload: Dict[str, Any] = {
        "game_id": game_id,
        "league_level_id": league_level_id,
        "league_year_id": league_year_id,
        "season_week": season_week,
        "season_subweek": season_subweek,
        "ballpark": ballpark,
        "home_side": home_side,
        "away_side": away_side,
    }

    if random_seed is not None:
        payload["random_seed"] = str(random_seed)

    return payload


def build_game_payload(conn, game_id: int) -> Dict[str, Any]:
    """
    Build the full engine payload for a single game_id.

    Returns a structure matching the weekly batch format, with the game
    placed in subweek 'a'. This ensures the engine always receives a
    consistent payload shape regardless of single vs. weekly simulation.

    Structure:
        {
            "league_year_id": 1,
            "season_week": 1,
            "league_level": 9,
            "total_games": 1,
            "game_constants": {...},
            "level_configs": {"9": {...}},
            "rules": {"9": {...}},
            "injury_types": [...],
            "subweeks": {
                "a": [game_payload],
                "b": [],
                "c": [],
                "d": []
            }
        }
    """
    # Build the core game data
    game_core = build_game_payload_core(conn, game_id)

    league_level_id = game_core["league_level_id"]
    league_year_id = game_core["league_year_id"]
    season_week = game_core["season_week"]

    # Load static game constants (cached, same for all games)
    game_constants = get_game_constants(conn)

    # Load level-specific config from normalized tables
    level_config = get_level_config_normalized(conn, league_level_id)
    level_configs = {str(league_level_id): level_config}

    # Load rules for this level
    rules = _get_level_rules_for_league(conn, league_level_id)
    rules_by_level = {str(league_level_id): rules}

    # Load injury type reference data
    injury_types = get_all_injury_types(conn)

    return {
        "league_year_id": league_year_id,
        "season_week": season_week,
        "league_level": league_level_id,
        "total_games": 1,
        "game_constants": game_constants,
        "level_configs": level_configs,
        "rules": rules_by_level,
        "injury_types": injury_types,
        "subweeks": {
            "a": [game_core],
            "b": [],
            "c": [],
            "d": [],
        },
    }


# -------------------------------------------------------------------
# Post-game: store results + update player state
# -------------------------------------------------------------------

_GAME_RESULT_INSERT = None  # lazy-built on first use


def _store_game_results(
    conn,
    results: List[Dict[str, Any]],
    payloads: List[Dict[str, Any]],
    games: List[Any],
) -> int:
    """
    Persist game scores/outcomes from the engine into the game_results table.

    Args:
        conn:     Active SQLAlchemy connection (caller manages commit).
        results:  Engine result dicts (game_id, home_score, away_score, winner).
        payloads: Payload dicts built by build_game_payload_core (same order as results).
        games:    Original gamelist rows for this subweek (contain season FK, league_level).

    Returns:
        Number of game_result rows inserted.
    """
    from sqlalchemy import text as sa_text

    if not results:
        return 0

    # Build lookup: game_id → payload, game_id → game_row
    payload_by_gid: Dict[int, Dict[str, Any]] = {}
    for p in payloads:
        gid = p.get("game_id")
        if gid is not None:
            payload_by_gid[int(gid)] = p

    game_row_by_gid: Dict[int, Any] = {}
    for g in games:
        gid = g.get("id") if isinstance(g, dict) else g["id"]
        game_row_by_gid[int(gid)] = g

    # Collect all team IDs so we can bulk-load org IDs
    all_team_ids: set[int] = set()
    for p in payloads:
        hs = p.get("home_side") or {}
        as_ = p.get("away_side") or {}
        if hs.get("team_id"):
            all_team_ids.add(int(hs["team_id"]))
        if as_.get("team_id"):
            all_team_ids.add(int(as_["team_id"]))

    # Bulk-load team → org mapping
    org_by_team: Dict[int, int] = {}
    if all_team_ids:
        tables = _get_core_tables()
        teams_tbl = tables["teams"]
        rows = (
            conn.execute(
                select(teams_tbl.c.id, teams_tbl.c.orgID)
                .where(teams_tbl.c.id.in_(list(all_team_ids)))
            )
            .mappings()
            .all()
        )
        for row in rows:
            org_by_team[int(row["id"])] = int(row["orgID"])

    insert_sql = sa_text("""
        INSERT INTO game_results
            (game_id, season, league_level, season_week, season_subweek,
             home_team_id, away_team_id, home_score, away_score,
             winning_team_id, losing_team_id, winning_org_id, losing_org_id,
             game_outcome, boxscore_json, play_by_play_json, game_type, completed_at)
        VALUES
            (:game_id, :season, :league_level, :season_week, :season_subweek,
             :home_team_id, :away_team_id, :home_score, :away_score,
             :winning_team_id, :losing_team_id, :winning_org_id, :losing_org_id,
             :game_outcome, :boxscore_json, :play_by_play_json, :game_type, NOW())
        AS new_row ON DUPLICATE KEY UPDATE
            home_score         = new_row.home_score,
            away_score         = new_row.away_score,
            winning_team_id    = new_row.winning_team_id,
            losing_team_id     = new_row.losing_team_id,
            winning_org_id     = new_row.winning_org_id,
            losing_org_id      = new_row.losing_org_id,
            game_outcome       = new_row.game_outcome,
            boxscore_json      = new_row.boxscore_json,
            play_by_play_json  = new_row.play_by_play_json,
            game_type          = new_row.game_type,
            completed_at       = NOW()
    """)

    count = 0
    for result in results:
        game_id = result.get("game_id")
        if game_id is None:
            continue
        game_id = int(game_id)

        payload = payload_by_gid.get(game_id)
        game_row = game_row_by_gid.get(game_id)
        if not payload or game_row is None:
            logger.warning(
                "store_game_results: no payload/game_row for game_id=%s, skipping",
                game_id,
            )
            continue

        home_side = payload.get("home_side") or {}
        away_side = payload.get("away_side") or {}
        home_team_id = int(home_side.get("team_id", 0))
        away_team_id = int(away_side.get("team_id", 0))

        # Engine nests scores inside result["result"]
        game_result_data = result.get("result") or {}
        home_score = int(game_result_data.get("home_score", 0))
        away_score = int(game_result_data.get("away_score", 0))

        # Also check top-level score fields as fallback
        if home_score == 0 and away_score == 0:
            home_score = int(result.get("home_score", 0))
            away_score = int(result.get("away_score", 0))

        if home_score == 0 and away_score == 0:
            logger.warning(
                "store_game_results: game_id=%s has 0-0 scores. "
                "result keys=%s, result['result'] keys=%s",
                game_id, list(result.keys()),
                list(game_result_data.keys()) if game_result_data else "empty"
            )

        # Determine outcome from scores (most reliable) with engine hint as fallback
        winner = str(game_result_data.get("winning_team", "")).lower()
        if not winner:
            winner = str(result.get("winning_team", "")).lower()
        if home_score > away_score or winner == "home":
            game_outcome = "HOME_WIN"
            winning_team_id = home_team_id
            losing_team_id = away_team_id
        elif away_score > home_score or winner == "away":
            game_outcome = "AWAY_WIN"
            winning_team_id = away_team_id
            losing_team_id = home_team_id
        else:
            game_outcome = "TIE"
            winning_team_id = None
            losing_team_id = None

        winning_org_id = org_by_team.get(winning_team_id) if winning_team_id else None
        losing_org_id = org_by_team.get(losing_team_id) if losing_team_id else None

        # Get season FK and league_level from the original gamelist row
        season_id = int(game_row.get("season") if isinstance(game_row, dict)
                        else game_row["season"])
        league_level = int(game_row.get("league_level") if isinstance(game_row, dict)
                           else game_row["league_level"])
        season_week = int(game_row.get("season_week") if isinstance(game_row, dict)
                          else game_row["season_week"])
        season_subweek = str(
            (game_row.get("season_subweek") if isinstance(game_row, dict)
             else game_row["season_subweek"]) or "a"
        )
        game_type = str(
            (game_row.get("game_type") if isinstance(game_row, dict)
             else game_row["game_type"]) or "regular"
        )

        # Serialize boxscore and play-by-play from engine result
        # Check both top-level and nested result dict
        boxscore_raw = result.get("boxscore") or game_result_data.get("boxscore")
        pbp_raw = result.get("play_by_play") or game_result_data.get("play_by_play")
        boxscore_str = json.dumps(boxscore_raw) if boxscore_raw else None
        pbp_trimmed = _trim_play_by_play(pbp_raw) if pbp_raw else None
        pbp_str = json.dumps(pbp_trimmed) if pbp_trimmed else None

        try:
            conn.execute(insert_sql, {
                "game_id": game_id,
                "season": season_id,
                "league_level": league_level,
                "season_week": season_week,
                "season_subweek": season_subweek,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "home_score": home_score,
                "away_score": away_score,
                "winning_team_id": winning_team_id,
                "losing_team_id": losing_team_id,
                "winning_org_id": winning_org_id,
                "losing_org_id": losing_org_id,
                "game_outcome": game_outcome,
                "boxscore_json": boxscore_str,
                "play_by_play_json": pbp_str,
                "game_type": game_type,
            })
            count += 1
        except Exception:
            logger.exception(
                "store_game_results: INSERT failed for game_id=%s", game_id
            )

    logger.info("store_game_results: inserted/updated %d game result rows", count)
    return count


def _store_game_results_bulk(
    conn,
    results: List[Dict[str, Any]],
    payloads: List[Dict[str, Any]],
    games: List[Any],
) -> int:
    """
    Bulk version of _store_game_results — collects all params, one executemany call.
    """
    from sqlalchemy import text as sa_text

    if not results:
        return 0

    payload_by_gid: Dict[int, Dict[str, Any]] = {}
    for p in payloads:
        gid = p.get("game_id")
        if gid is not None:
            payload_by_gid[int(gid)] = p

    game_row_by_gid: Dict[int, Any] = {}
    for g in games:
        gid = g.get("id") if isinstance(g, dict) else g["id"]
        game_row_by_gid[int(gid)] = g

    # Build org mapping from payloads (already have org_id in team sides)
    org_by_team: Dict[int, int] = {}
    for p in payloads:
        for side_key in ("home_side", "away_side"):
            side = p.get(side_key) or {}
            tid = side.get("team_id")
            oid = side.get("org_id")
            if tid and oid:
                org_by_team[int(tid)] = int(oid)

    # If we still need org mappings, bulk-load from DB
    all_team_ids = set()
    for p in payloads:
        for side_key in ("home_side", "away_side"):
            side = p.get(side_key) or {}
            tid = side.get("team_id")
            if tid and int(tid) not in org_by_team:
                all_team_ids.add(int(tid))

    if all_team_ids:
        tables = _get_core_tables()
        teams_tbl = tables["teams"]
        rows = conn.execute(
            select(teams_tbl.c.id, teams_tbl.c.orgID)
            .where(teams_tbl.c.id.in_(list(all_team_ids)))
        ).mappings().all()
        for row in rows:
            org_by_team[int(row["id"])] = int(row["orgID"])

    insert_sql = sa_text("""
        INSERT INTO game_results
            (game_id, season, league_level, season_week, season_subweek,
             home_team_id, away_team_id, home_score, away_score,
             winning_team_id, losing_team_id, winning_org_id, losing_org_id,
             game_outcome, boxscore_json, play_by_play_json, game_type, completed_at)
        VALUES
            (:game_id, :season, :league_level, :season_week, :season_subweek,
             :home_team_id, :away_team_id, :home_score, :away_score,
             :winning_team_id, :losing_team_id, :winning_org_id, :losing_org_id,
             :game_outcome, :boxscore_json, :play_by_play_json, :game_type, NOW())
        AS new_row ON DUPLICATE KEY UPDATE
            home_score         = new_row.home_score,
            away_score         = new_row.away_score,
            winning_team_id    = new_row.winning_team_id,
            losing_team_id     = new_row.losing_team_id,
            winning_org_id     = new_row.winning_org_id,
            losing_org_id      = new_row.losing_org_id,
            game_outcome       = new_row.game_outcome,
            boxscore_json      = new_row.boxscore_json,
            play_by_play_json  = new_row.play_by_play_json,
            game_type          = new_row.game_type,
            completed_at       = NOW()
    """)

    all_params = []

    for result in results:
        game_id = result.get("game_id")
        if game_id is None:
            continue
        game_id = int(game_id)

        payload = payload_by_gid.get(game_id)
        game_row = game_row_by_gid.get(game_id)
        if not payload or game_row is None:
            continue

        home_side = payload.get("home_side") or {}
        away_side = payload.get("away_side") or {}
        home_team_id = int(home_side.get("team_id", 0))
        away_team_id = int(away_side.get("team_id", 0))

        game_result_data = result.get("result") or {}
        home_score = int(game_result_data.get("home_score", 0))
        away_score = int(game_result_data.get("away_score", 0))

        if home_score == 0 and away_score == 0:
            home_score = int(result.get("home_score", 0))
            away_score = int(result.get("away_score", 0))

        winner = str(game_result_data.get("winning_team", "")).lower()
        if not winner:
            winner = str(result.get("winning_team", "")).lower()
        if home_score > away_score or winner == "home":
            game_outcome = "HOME_WIN"
            winning_team_id = home_team_id
            losing_team_id = away_team_id
        elif away_score > home_score or winner == "away":
            game_outcome = "AWAY_WIN"
            winning_team_id = away_team_id
            losing_team_id = home_team_id
        else:
            game_outcome = "TIE"
            winning_team_id = None
            losing_team_id = None

        winning_org_id = org_by_team.get(winning_team_id) if winning_team_id else None
        losing_org_id = org_by_team.get(losing_team_id) if losing_team_id else None

        season_id = int(game_row.get("season") if isinstance(game_row, dict) else game_row["season"])
        league_level = int(game_row.get("league_level") if isinstance(game_row, dict) else game_row["league_level"])
        season_week = int(game_row.get("season_week") if isinstance(game_row, dict) else game_row["season_week"])
        season_subweek = str((game_row.get("season_subweek") if isinstance(game_row, dict) else game_row["season_subweek"]) or "a")
        game_type = str((game_row.get("game_type") if isinstance(game_row, dict) else game_row["game_type"]) or "regular")

        boxscore_raw = result.get("boxscore") or game_result_data.get("boxscore")
        pbp_raw = result.get("play_by_play") or game_result_data.get("play_by_play")
        boxscore_str = json.dumps(boxscore_raw) if boxscore_raw else None
        pbp_trimmed = _trim_play_by_play(pbp_raw) if pbp_raw else None
        pbp_str = json.dumps(pbp_trimmed) if pbp_trimmed else None

        all_params.append({
            "game_id": game_id,
            "season": season_id,
            "league_level": league_level,
            "season_week": season_week,
            "season_subweek": season_subweek,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_score": home_score,
            "away_score": away_score,
            "winning_team_id": winning_team_id,
            "losing_team_id": losing_team_id,
            "winning_org_id": winning_org_id,
            "losing_org_id": losing_org_id,
            "game_outcome": game_outcome,
            "boxscore_json": boxscore_str,
            "play_by_play_json": pbp_str,
            "game_type": game_type,
        })

    if not all_params:
        return 0

    # Try bulk insert in a savepoint so failures don't poison the connection
    try:
        with conn.begin_nested():
            conn.execute(insert_sql, all_params)
        logger.info("store_game_results_bulk: inserted/updated %d game result rows", len(all_params))
        return len(all_params)
    except Exception:
        logger.warning(
            "store_game_results_bulk: bulk INSERT failed (%d rows), falling back to row-by-row",
            len(all_params),
        )

    # Row-by-row fallback — each row in its own savepoint so one bad row
    # (or a connection hiccup on a very large payload) doesn't lose them all
    inserted = 0
    for params in all_params:
        try:
            with conn.begin_nested():
                conn.execute(insert_sql, [params])
            inserted += 1
        except Exception:
            logger.exception(
                "store_game_results_bulk: row-by-row INSERT failed for game_id %s",
                params.get("game_id"),
            )

    logger.info(
        "store_game_results_bulk: row-by-row inserted %d / %d game result rows",
        inserted, len(all_params),
    )
    return inserted


def _update_playoff_series_bulk(
    conn,
    results: List[Dict[str, Any]],
    payloads: List[Dict[str, Any]],
    games: List[Any],
) -> List[Dict[str, Any]]:
    """
    After storing game results, update playoff_series win counts for any
    playoff games in this batch.  Automatically generates the next game
    for active series.

    Returns list of series update dicts (one per playoff game processed).
    """
    from services.playoffs import update_series_after_game

    # Build game_type lookup from gamelist rows
    game_type_by_id: Dict[int, str] = {}
    for g in games:
        gid = int(g["id"] if isinstance(g, dict) else g["id"])
        gt = str((g.get("game_type") if isinstance(g, dict) else g["game_type"]) or "regular")
        game_type_by_id[gid] = gt

    updates = []
    for result in results:
        game_id = result.get("game_id")
        if game_id is None:
            continue
        game_id = int(game_id)

        if game_type_by_id.get(game_id) != "playoff":
            continue

        try:
            update = update_series_after_game(conn, game_id)
            if update:
                updates.append(update)
                logger.info(
                    "playoff_series auto-update for game %d: series %d → %d-%d (%s)",
                    game_id, update["series_id"],
                    update["wins_a"], update["wins_b"], update["status"],
                )
        except Exception:
            logger.exception("playoff_series update failed for game %d", game_id)

    return updates


def _normalize_engine_effects(effects: Dict[str, Any]) -> Dict[str, float]:
    """
    Flatten engine injury effects into a simple {attr: multiplier} dict.

    The engine returns effects in nested format:
        {"speed": {"original": 75, "modified": 52.5, "multiplier": 0.7}}

    We extract just the multiplier for storage in malus_json:
        {"speed": 0.7}

    If a value is already a plain number (backwards compat), keep it as-is.
    """
    out: Dict[str, float] = {}
    for attr, val in effects.items():
        if isinstance(val, dict):
            m = val.get("multiplier")
            if m is not None:
                try:
                    out[attr] = float(m)
                except (TypeError, ValueError):
                    continue
        else:
            try:
                out[attr] = float(val)
            except (TypeError, ValueError):
                continue
    return out


def _persist_pregame_injuries(
    conn,
    pregame_injuries: List[Dict[str, Any]],
    league_year_id: int,
) -> int:
    """
    Persist pregame injuries to player_injury_events and player_injury_state.

    Called immediately after roll_pregame_injuries_for_team so that the
    rolled injuries are visible via the roster/player endpoints for the
    duration of the subweek (or until they expire via weekly advancement).

    Returns count of injuries persisted.
    """
    from sqlalchemy import text as sa_text

    if not pregame_injuries:
        return 0

    injury_insert = sa_text("""
        INSERT INTO player_injury_events
            (player_id, injury_type_id, league_year_id, weeks_assigned,
             weeks_remaining, malus_json)
        VALUES
            (:player_id, :injury_type_id, :league_year_id, :weeks_assigned,
             :weeks_remaining, :malus_json)
    """)
    injury_state_upsert = sa_text("""
        INSERT INTO player_injury_state
            (player_id, status, current_event_id, weeks_remaining, last_updated_at)
        VALUES
            (:player_id, 'injured', :event_id, :weeks_remaining, NOW())
        ON DUPLICATE KEY UPDATE
            status           = 'injured',
            current_event_id = IF(:weeks_remaining > weeks_remaining,
                                  :event_id, current_event_id),
            weeks_remaining  = GREATEST(:weeks_remaining, weeks_remaining),
            last_updated_at  = NOW()
    """)

    count = 0
    for inj in pregame_injuries:
        pid = inj.get("player_id")
        if pid is None:
            continue
        pid = int(pid)
        injury_type_id = int(inj.get("injury_type_id", 0))
        duration_weeks = int(inj.get("duration_weeks", 1))
        effects = inj.get("effects") or {}

        try:
            ev_result = conn.execute(injury_insert, {
                "player_id": pid,
                "injury_type_id": injury_type_id,
                "league_year_id": league_year_id,
                "weeks_assigned": duration_weeks,
                "weeks_remaining": duration_weeks,
                "malus_json": json.dumps(effects),
            })
            event_id = ev_result.lastrowid
            conn.execute(injury_state_upsert, {
                "player_id": pid,
                "event_id": event_id,
                "weeks_remaining": duration_weeks,
            })
            count += 1
        except Exception:
            logger.exception(
                "_persist_pregame_injuries: failed for player %d", pid
            )

    if count:
        logger.info("_persist_pregame_injuries: persisted %d pregame injuries", count)
    return count


def _drain_stamina_and_persist_injuries(
    conn,
    results: List[Dict[str, Any]],
    league_year_id: int,
    injury_types: List[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """
    Per-level safe post-subweek updates: stamina drain + injury persistence.

    Stamina drain only touches players who actually played (from engine results).
    Injuries are player-scoped and level-isolated via roster constraints.

    Recovery is NOT done here — call _apply_global_stamina_recovery() once
    after all levels have finished their drain phase.

    injury_types: optional list of injury type dicts (from get_all_injury_types).
    When provided, effects are computed from impact_template_json if the engine
    does not return them — ensuring malus_json is never stored as "{}".
    """
    from sqlalchemy import text as sa_text

    # Build injury_type_id → row lookup AND code → id lookup for template fallback.
    # code lookup is needed because pregame injury entries from the engine omit injury_type_id.
    injury_type_map: Dict[int, Dict[str, Any]] = {}
    injury_code_to_id: Dict[str, int] = {}
    if injury_types:
        for it in injury_types:
            tid = it.get("id") or it.get("injury_type_id")
            if tid is not None:
                injury_type_map[int(tid)] = it
                code = it.get("code")
                if code:
                    injury_code_to_id[str(code)] = int(tid)

    injuries_persisted = 0
    drain_count = 0

    # --- 1. STAMINA DRAIN from engine stamina_cost ---
    # A player in both batters and pitchers has the same cost — use either, not sum.
    # Also track per-game costs so we can persist them for re-sim rollback.
    player_costs: Dict[int, int] = {}
    per_game_costs: Dict[int, Dict[int, int]] = {}  # game_id → {player_id: cost}
    for result in results:
        game_id = result.get("game_id")
        nested = result.get("result") or {}
        if game_id is None:
            game_id = nested.get("game_id") or (nested.get("result") or {}).get("id")
        stats = result.get("stats") or nested.get("stats")
        if not stats:
            continue
        game_costs: Dict[int, int] = {}
        for pid_str, p in (stats.get("pitchers") or {}).items():
            cost = p.get("stamina_cost")
            if cost is not None and int(cost) > 0:
                pid = int(pid_str)
                player_costs[pid] = int(cost)
                game_costs[pid] = int(cost)
        for pid_str, b in (stats.get("batters") or {}).items():
            pid = int(pid_str)
            if pid not in player_costs:
                cost = b.get("stamina_cost")
                if cost is not None and int(cost) > 0:
                    player_costs[pid] = int(cost)
            if pid not in game_costs:
                cost = b.get("stamina_cost")
                if cost is not None and int(cost) > 0:
                    game_costs[pid] = int(cost)
        if game_id is not None and game_costs:
            per_game_costs[int(game_id)] = game_costs

    if player_costs:
        drain_upsert = sa_text("""
            INSERT INTO player_fatigue_state
                (player_id, league_year_id, stamina, last_updated_at)
            VALUES
                (:player_id, :league_year_id, GREATEST(0, 100 - :cost), NOW())
            ON DUPLICATE KEY UPDATE
                stamina = GREATEST(0, stamina - :cost),
                last_updated_at = NOW()
        """)
        drain_params = [
            {"player_id": pid, "league_year_id": league_year_id, "cost": cost}
            for pid, cost in player_costs.items()
        ]
        try:
            conn.execute(drain_upsert, drain_params)
            drain_count = len(drain_params)
            logger.info(
                "drain_stamina: applied stamina drain to %d players "
                "(total cost: %d)", drain_count, sum(player_costs.values())
            )
        except Exception:
            logger.exception("drain_stamina: stamina drain failed")

    # Persist stamina_cost on per-game lines for re-sim rollback
    if per_game_costs:
        update_bat_cost = sa_text("""
            UPDATE game_batting_lines SET stamina_cost = :cost
            WHERE game_id = :game_id AND player_id = :player_id
        """)
        update_pitch_cost = sa_text("""
            UPDATE game_pitching_lines SET stamina_cost = :cost
            WHERE game_id = :game_id AND player_id = :player_id
        """)
        cost_params = []
        for gid, costs_map in per_game_costs.items():
            for pid, cost in costs_map.items():
                cost_params.append({"game_id": gid, "player_id": pid, "cost": cost})
        try:
            conn.execute(update_bat_cost, cost_params)
            conn.execute(update_pitch_cost, cost_params)
        except Exception:
            logger.debug("drain_stamina: stamina_cost column update skipped (column may not exist yet)")

    # --- 2. INJURY PERSISTENCE ---
    injury_insert = sa_text("""
        INSERT INTO player_injury_events
            (player_id, injury_type_id, league_year_id, gamelist_id,
             weeks_assigned, weeks_remaining, malus_json)
        VALUES
            (:player_id, :injury_type_id, :league_year_id, :gamelist_id,
             :weeks_assigned, :weeks_remaining, :malus_json)
    """)

    injury_state_upsert = sa_text("""
        INSERT INTO player_injury_state
            (player_id, status, current_event_id, weeks_remaining, last_updated_at)
        VALUES
            (:player_id, 'injured', :event_id, :weeks_remaining, NOW())
        ON DUPLICATE KEY UPDATE
            status           = 'injured',
            current_event_id = IF(:weeks_remaining > weeks_remaining,
                                  :event_id, current_event_id),
            weeks_remaining  = GREATEST(weeks_remaining, :weeks_remaining),
            last_updated_at  = NOW()
    """)

    for result in results:
        # Extract game_id for gamelist_id on injury events
        _r_nested = result.get("result") or {}
        _r_game_id = result.get("game_id") or _r_nested.get("game_id") or _r_nested.get("id")
        injuries = result.get("injuries") or []
        for inj in injuries:
            pid = inj.get("player_id")
            if pid is None:
                continue
            pid = int(pid)
            # injury_type_id is absent from pregame entries — fall back to code lookup
            raw_tid = inj.get("injury_type_id")
            if raw_tid:
                injury_type_id = int(raw_tid)
            else:
                code = inj.get("code") or ""
                injury_type_id = injury_code_to_id.get(str(code), 0)
                if not injury_type_id:
                    logger.warning(
                        "drain_stamina: no injury_type_id and unknown code %r for player %d — skipping",
                        code, pid,
                    )
                    continue
            duration_weeks = int(inj.get("duration_weeks", 1))
            effects = _normalize_engine_effects(inj.get("effects") or {})

            # stamina_pct is a backend roster-management attribute — the engine
            # handles in-game energy via stamina_cost, not as an injury effect.
            # We always derive stamina_pct from the injury type template so that
            # injured players are benched for the correct number of weeks.
            # Other template attributes (contact, speed, etc.) are also filled in
            # from the template for any attribute the engine did not return.
            if injury_type_id in injury_type_map:
                it_row = injury_type_map[injury_type_id]
                raw = it_row.get("impact_template_json") or "{}"
                try:
                    template = raw if isinstance(raw, dict) else json.loads(raw)
                    for attr, cfg in template.items():
                        if attr in effects:
                            continue  # keep engine-supplied value
                        if isinstance(cfg, dict):
                            min_pct = float(cfg.get("min_pct", 0))
                            max_pct = float(cfg.get("max_pct", 0))
                            rolled_pct = round(random.uniform(min_pct, max_pct), 2)
                            effects[attr] = max(0.0, 1.0 - rolled_pct)
                except (TypeError, ValueError, json.JSONDecodeError):
                    logger.warning(
                        "drain_stamina: failed to parse template for injury_type_id %d",
                        injury_type_id,
                    )

            logger.debug(
                "drain_stamina: player %d injury_type %d → effects=%s",
                pid, injury_type_id, effects,
            )

            try:
                ev_result = conn.execute(injury_insert, {
                    "player_id": pid,
                    "injury_type_id": injury_type_id,
                    "league_year_id": league_year_id,
                    "gamelist_id": int(_r_game_id) if _r_game_id is not None else None,
                    "weeks_assigned": duration_weeks,
                    "weeks_remaining": duration_weeks,
                    "malus_json": json.dumps(effects),
                })
                event_id = ev_result.lastrowid
                conn.execute(injury_state_upsert, {
                    "player_id": pid,
                    "event_id": event_id,
                    "weeks_remaining": duration_weeks,
                })
                injuries_persisted += 1
            except Exception:
                logger.exception(
                    "drain_stamina: injury persistence failed for player %d", pid
                )

    logger.info(
        "drain_stamina: %d drained, %d injuries persisted",
        drain_count, injuries_persisted,
    )
    return {"drain_count": drain_count, "injuries_persisted": injuries_persisted}


def _apply_global_stamina_recovery(
    conn,
    league_year_id: int,
    league_level: int | None = None,
) -> int:
    """
    Apply stamina recovery for ALL fatigued players in the league year.

    This must be called ONCE per subweek AFTER all levels have drained.
    Running it per-level would cause double-recovery.
    """
    from sqlalchemy import text as sa_text

    rec_cfg = _load_stamina_recovery_config(conn, league_level)
    logger.info(
        "global_recovery: config level=%s base=%.1f pitcher=%.1f",
        league_level, rec_cfg["base_recovery"], rec_cfg["base_recovery_pitcher"],
    )

    recovery_sql = sa_text("""
        UPDATE player_fatigue_state pfs
        JOIN simbbPlayers p ON p.id = pfs.player_id
        SET pfs.stamina = LEAST(100, pfs.stamina + ROUND(
            CASE WHEN p.ptype = 'Pitcher' THEN :base_recovery_pitcher
                 ELSE :base_recovery
            END *
            CASE p.durability
                WHEN 'Iron Man'      THEN :mult_iron_man
                WHEN 'Dependable'    THEN :mult_dependable
                WHEN 'Normal'        THEN :mult_normal
                WHEN 'Undependable'  THEN :mult_undependable
                WHEN 'Tires Easily'  THEN :mult_tires_easily
                ELSE :mult_normal
            END)),
            pfs.last_updated_at = NOW()
        WHERE pfs.league_year_id = :league_year_id
          AND pfs.stamina < 100
    """)

    recovery_count = 0
    try:
        rest_result = conn.execute(recovery_sql, {
            "base_recovery": rec_cfg["base_recovery"],
            "base_recovery_pitcher": rec_cfg["base_recovery_pitcher"],
            "mult_iron_man": rec_cfg["Iron Man"],
            "mult_dependable": rec_cfg["Dependable"],
            "mult_normal": rec_cfg["Normal"],
            "mult_undependable": rec_cfg["Undependable"],
            "mult_tires_easily": rec_cfg["Tires Easily"],
            "league_year_id": league_year_id,
        })
        recovery_count = rest_result.rowcount
        logger.info("global_recovery: %d players recovered stamina", recovery_count)
    except Exception:
        logger.exception("global_recovery: rest recovery failed")

    return recovery_count


# Legacy wrapper — kept for _update_player_state_after_subweek compatibility
def _update_player_state_bulk(
    conn,
    results: List[Dict[str, Any]],
    league_year_id: int,
    league_level: int | None = None,
    injury_types: List[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """
    Combined drain + recovery + injuries.  Used by legacy single-level code path.
    For parallel processing, use _drain_stamina_and_persist_injuries() +
    _apply_global_stamina_recovery() separately.
    """
    counts = _drain_stamina_and_persist_injuries(conn, results, league_year_id, injury_types=injury_types)
    recovery_count = _apply_global_stamina_recovery(conn, league_year_id, league_level)
    counts["recovery_count"] = recovery_count
    return counts


# Stamina recovery defaults — used when level_game_config has no row
_REST_RECOVERY_PER_SUBWEEK = 5
_DURABILITY_RECOVERY_MULT = {
    "Iron Man":      1.5,
    "Dependable":    1.25,
    "Normal":        1.0,
    "Undependable":  0.75,
    "Tires Easily":  0.5,
}


def _load_stamina_recovery_config(conn, league_level: int = None) -> dict:
    """
    Load stamina recovery config from level_game_config.

    Returns dict with base_recovery (position players), base_recovery_pitcher,
    and durability multipliers. Falls back to hardcoded defaults if no config
    row exists.
    """
    from sqlalchemy import text as sa_text

    if league_level is not None:
        row = conn.execute(sa_text(
            "SELECT stamina_recovery_per_subweek, "
            "stamina_recovery_pitcher_per_subweek, "
            "durability_mult_iron_man, durability_mult_dependable, "
            "durability_mult_normal, durability_mult_undependable, "
            "durability_mult_tires_easily "
            "FROM level_game_config WHERE league_level = :ll"
        ), {"ll": league_level}).mappings().first()
    else:
        # No specific level — try highest level config, fall back to defaults
        try:
            row = conn.execute(sa_text(
                "SELECT stamina_recovery_per_subweek, "
                "stamina_recovery_pitcher_per_subweek, "
                "durability_mult_iron_man, durability_mult_dependable, "
                "durability_mult_normal, durability_mult_undependable, "
                "durability_mult_tires_easily "
                "FROM level_game_config ORDER BY league_level DESC LIMIT 1"
            )).mappings().first()
        except Exception:
            row = None

    if row and row.get("stamina_recovery_per_subweek") is not None:
        return {
            "base_recovery": float(row["stamina_recovery_per_subweek"]),
            "base_recovery_pitcher": float(row.get("stamina_recovery_pitcher_per_subweek") or row["stamina_recovery_per_subweek"]),
            "Iron Man": float(row["durability_mult_iron_man"]),
            "Dependable": float(row["durability_mult_dependable"]),
            "Normal": float(row["durability_mult_normal"]),
            "Undependable": float(row["durability_mult_undependable"]),
            "Tires Easily": float(row["durability_mult_tires_easily"]),
        }

    return {
        "base_recovery": _REST_RECOVERY_PER_SUBWEEK,
        "base_recovery_pitcher": _REST_RECOVERY_PER_SUBWEEK,
        **_DURABILITY_RECOVERY_MULT,
    }


# -------------------------------------------------------------------
# Re-simulation idempotency: detect + rollback prior results
# -------------------------------------------------------------------

def _detect_resim_games(conn, game_ids: List[int]) -> List[int]:
    """
    Return the subset of game_ids that already have a row in game_results.
    Those games are being re-simulated and need prior data rolled back.
    """
    from sqlalchemy import text as sa_text

    if not game_ids:
        return []

    placeholders = ", ".join(f":g{i}" for i in range(len(game_ids)))
    params = {f"g{i}": gid for i, gid in enumerate(game_ids)}

    rows = conn.execute(sa_text(
        f"SELECT game_id FROM game_results WHERE game_id IN ({placeholders})"
    ), params).fetchall()

    return [int(r[0]) for r in rows]


def _rollback_prior_results(
    conn,
    resim_game_ids: List[int],
    league_year_id: int,
    season_week: int,
) -> Dict[str, Any]:
    """
    Undo the side-effects of a previous simulation for the given game_ids
    so that re-simulation is idempotent.

    Steps:
      1. Reverse season batting stats using old game_batting_lines
      2. Reverse season pitching stats using old game_pitching_lines
      3. Reverse season fielding stats using old game_fielding_lines
      4. Reverse stamina drain using stamina_cost from per-game lines
      5. Reverse position usage (decrement starts_this_week)
      6. Reverse playoff series win counts
      7. Delete old injury events for these games
      8. Delete old per-game lines, substitutions
    """
    from sqlalchemy import text as sa_text

    if not resim_game_ids:
        return {"rolled_back": 0}

    ph = ", ".join(f":g{i}" for i in range(len(resim_game_ids)))
    gp = {f"g{i}": gid for i, gid in enumerate(resim_game_ids)}

    counts: Dict[str, int] = {}

    # ---------------------------------------------------------------
    # 1) Reverse season BATTING stats from old game_batting_lines
    # ---------------------------------------------------------------
    old_bat = conn.execute(sa_text(f"""
        SELECT player_id, league_year_id, team_id,
               COUNT(*) AS game_count,
               SUM(at_bats) AS at_bats, SUM(runs) AS runs,
               SUM(hits) AS hits, SUM(doubles_hit) AS doubles_hit,
               SUM(triples) AS triples, SUM(home_runs) AS home_runs,
               SUM(inside_the_park_hr) AS inside_the_park_hr,
               SUM(rbi) AS rbi, SUM(walks) AS walks,
               SUM(strikeouts) AS strikeouts,
               SUM(stolen_bases) AS stolen_bases,
               SUM(caught_stealing) AS caught_stealing
        FROM game_batting_lines
        WHERE game_id IN ({ph})
        GROUP BY player_id, league_year_id, team_id
    """), gp).mappings().all()

    if old_bat:
        reverse_bat = sa_text("""
            UPDATE player_batting_stats SET
                games          = GREATEST(0, games - :game_count),
                at_bats        = GREATEST(0, at_bats - :at_bats),
                runs           = GREATEST(0, runs - :runs),
                hits           = GREATEST(0, hits - :hits),
                doubles_hit    = GREATEST(0, doubles_hit - :doubles_hit),
                triples        = GREATEST(0, triples - :triples),
                home_runs      = GREATEST(0, home_runs - :home_runs),
                inside_the_park_hr = GREATEST(0, inside_the_park_hr - :inside_the_park_hr),
                rbi            = GREATEST(0, rbi - :rbi),
                walks          = GREATEST(0, walks - :walks),
                strikeouts     = GREATEST(0, strikeouts - :strikeouts),
                stolen_bases   = GREATEST(0, stolen_bases - :stolen_bases),
                caught_stealing = GREATEST(0, caught_stealing - :caught_stealing)
            WHERE player_id = :player_id
              AND league_year_id = :league_year_id
              AND team_id = :team_id
        """)
        for row in old_bat:
            conn.execute(reverse_bat, dict(row))
        counts["batting_reversed"] = len(old_bat)

    # ---------------------------------------------------------------
    # 2) Reverse season PITCHING stats from old game_pitching_lines
    # ---------------------------------------------------------------
    old_pitch = conn.execute(sa_text(f"""
        SELECT player_id, league_year_id, team_id,
               COUNT(*) AS game_count,
               SUM(games_started) AS games_started,
               SUM(win) AS win, SUM(loss) AS loss,
               SUM(save_recorded) AS save_recorded,
               SUM(hold) AS hold, SUM(blown_save) AS blown_save,
               SUM(quality_start) AS quality_start,
               SUM(innings_pitched_outs) AS innings_pitched_outs,
               SUM(hits_allowed) AS hits_allowed,
               SUM(runs_allowed) AS runs_allowed,
               SUM(earned_runs) AS earned_runs,
               SUM(walks) AS walks, SUM(strikeouts) AS strikeouts,
               SUM(home_runs_allowed) AS home_runs_allowed,
               SUM(inside_the_park_hr_allowed) AS inside_the_park_hr_allowed
        FROM game_pitching_lines
        WHERE game_id IN ({ph})
        GROUP BY player_id, league_year_id, team_id
    """), gp).mappings().all()

    if old_pitch:
        reverse_pitch = sa_text("""
            UPDATE player_pitching_stats SET
                games              = GREATEST(0, games - :game_count),
                games_started      = GREATEST(0, games_started - :games_started),
                wins               = GREATEST(0, wins - :win),
                losses             = GREATEST(0, losses - :loss),
                saves              = GREATEST(0, saves - :save_recorded),
                holds              = GREATEST(0, holds - :hold),
                blown_saves        = GREATEST(0, blown_saves - :blown_save),
                quality_starts     = GREATEST(0, quality_starts - :quality_start),
                innings_pitched_outs = GREATEST(0, innings_pitched_outs - :innings_pitched_outs),
                hits_allowed       = GREATEST(0, hits_allowed - :hits_allowed),
                runs_allowed       = GREATEST(0, runs_allowed - :runs_allowed),
                earned_runs        = GREATEST(0, earned_runs - :earned_runs),
                walks              = GREATEST(0, walks - :walks),
                strikeouts         = GREATEST(0, strikeouts - :strikeouts),
                home_runs_allowed  = GREATEST(0, home_runs_allowed - :home_runs_allowed),
                inside_the_park_hr_allowed = GREATEST(0, inside_the_park_hr_allowed - :inside_the_park_hr_allowed)
            WHERE player_id = :player_id
              AND league_year_id = :league_year_id
              AND team_id = :team_id
        """)
        for row in old_pitch:
            conn.execute(reverse_pitch, dict(row))
        counts["pitching_reversed"] = len(old_pitch)

    # ---------------------------------------------------------------
    # 3) Reverse season FIELDING stats from old game_fielding_lines
    # ---------------------------------------------------------------
    try:
        old_field = conn.execute(sa_text(f"""
            SELECT player_id, league_year_id, team_id, position_code,
                   COUNT(*) AS game_count,
                   SUM(innings) AS innings, SUM(putouts) AS putouts,
                   SUM(assists) AS assists, SUM(errors) AS errors
            FROM game_fielding_lines
            WHERE game_id IN ({ph})
            GROUP BY player_id, league_year_id, team_id, position_code
        """), gp).mappings().all()

        if old_field:
            reverse_field = sa_text("""
                UPDATE player_fielding_stats SET
                    games   = GREATEST(0, games - :game_count),
                    innings = GREATEST(0, innings - :innings),
                    putouts = GREATEST(0, putouts - :putouts),
                    assists = GREATEST(0, assists - :assists),
                    errors  = GREATEST(0, errors - :errors)
                WHERE player_id = :player_id
                  AND league_year_id = :league_year_id
                  AND team_id = :team_id
                  AND position_code = :position_code
            """)
            for row in old_field:
                conn.execute(reverse_field, dict(row))
            counts["fielding_reversed"] = len(old_field)
    except Exception:
        logger.debug("rollback_prior_results: game_fielding_lines table not available — skipping fielding reversal")

    # ---------------------------------------------------------------
    # 4) Reverse STAMINA drain using stored stamina_cost
    # ---------------------------------------------------------------
    # Collect stamina costs from both batting and pitching lines
    # (a player in both has the same cost — use MAX to avoid double-restore)
    old_costs = conn.execute(sa_text(f"""
        SELECT player_id, MAX(stamina_cost) AS stamina_cost
        FROM (
            SELECT player_id, stamina_cost FROM game_batting_lines
            WHERE game_id IN ({ph}) AND stamina_cost IS NOT NULL
            UNION ALL
            SELECT player_id, stamina_cost FROM game_pitching_lines
            WHERE game_id IN ({ph}) AND stamina_cost IS NOT NULL
        ) combined
        GROUP BY player_id
    """), gp).mappings().all()

    if old_costs:
        restore_stamina = sa_text("""
            UPDATE player_fatigue_state
            SET stamina = LEAST(100, stamina + :cost),
                last_updated_at = NOW()
            WHERE player_id = :player_id AND league_year_id = :league_year_id
        """)
        for row in old_costs:
            cost = row["stamina_cost"]
            if cost and int(cost) > 0:
                conn.execute(restore_stamina, {
                    "player_id": int(row["player_id"]),
                    "league_year_id": league_year_id,
                    "cost": int(cost),
                })
        counts["stamina_restored"] = len(old_costs)

    # ---------------------------------------------------------------
    # 5) Reverse POSITION USAGE
    # ---------------------------------------------------------------
    # We know team_ids and the week — decrement by reading old batting lines
    # which have position_code per player per game
    old_usage = conn.execute(sa_text(f"""
        SELECT gbl.player_id, gbl.team_id, gbl.position_code,
               gr.home_team_id, gr.away_team_id,
               COUNT(*) AS start_count
        FROM game_batting_lines gbl
        JOIN game_results gr ON gr.game_id = gbl.game_id
        WHERE gbl.game_id IN ({ph})
          AND gbl.position_code IS NOT NULL
          AND gbl.position_code != ''
        GROUP BY gbl.player_id, gbl.team_id, gbl.position_code,
                 gr.home_team_id, gr.away_team_id
    """), gp).mappings().all()

    if old_usage:
        # We need vs_hand but it's not stored in game_batting_lines.
        # Approximate by decrementing across both hands if needed.
        # Since position_usage_week is per (player, team, pos, vs_hand, week),
        # decrement all matching rows proportionally.
        decr_usage = sa_text("""
            UPDATE player_position_usage_week
            SET starts_this_week = GREATEST(0, starts_this_week - :start_count)
            WHERE league_year_id = :league_year_id
              AND season_week = :season_week
              AND team_id = :team_id
              AND player_id = :player_id
              AND position_code = :position_code
        """)
        for row in old_usage:
            pos = str(row["position_code"]).lower()
            # Normalize position codes to match usage table enum
            pos_map = {
                "c": "c", "1b": "fb", "2b": "sb", "3b": "tb", "ss": "ss",
                "lf": "lf", "cf": "cf", "rf": "rf", "dh": "dh", "p": "p",
                "fb": "fb", "sb": "sb", "tb": "tb",
            }
            usage_pos = pos_map.get(pos)
            if not usage_pos:
                continue
            conn.execute(decr_usage, {
                "league_year_id": league_year_id,
                "season_week": season_week,
                "team_id": int(row["team_id"]),
                "player_id": int(row["player_id"]),
                "position_code": usage_pos,
                "start_count": int(row["start_count"]),
            })
        counts["usage_reversed"] = len(old_usage)

    # ---------------------------------------------------------------
    # 6) Reverse PLAYOFF SERIES win counts
    # ---------------------------------------------------------------
    old_playoff = conn.execute(sa_text(f"""
        SELECT gr.game_id, gr.home_team_id, gr.away_team_id,
               gr.winning_team_id, gr.game_type
        FROM game_results gr
        WHERE gr.game_id IN ({ph}) AND gr.game_type = 'playoff'
    """), gp).mappings().all()

    for pg in old_playoff:
        old_winner = pg["winning_team_id"]
        if not old_winner:
            continue
        old_winner = int(old_winner)
        home_tid = int(pg["home_team_id"])
        away_tid = int(pg["away_team_id"])

        series = conn.execute(sa_text("""
            SELECT id, team_a_id, team_b_id, wins_a, wins_b, status
            FROM playoff_series
            WHERE (team_a_id = :home OR team_a_id = :away)
              AND (team_b_id = :home OR team_b_id = :away)
            ORDER BY id DESC LIMIT 1
        """), {"home": home_tid, "away": away_tid}).mappings().first()

        if not series:
            continue

        sid = int(series["id"])
        team_a = int(series["team_a_id"])
        if old_winner == team_a:
            conn.execute(sa_text("""
                UPDATE playoff_series
                SET wins_a = GREATEST(0, wins_a - 1),
                    status = 'active', winner_team_id = NULL
                WHERE id = :sid
            """), {"sid": sid})
        else:
            conn.execute(sa_text("""
                UPDATE playoff_series
                SET wins_b = GREATEST(0, wins_b - 1),
                    status = 'active', winner_team_id = NULL
                WHERE id = :sid
            """), {"sid": sid})
    counts["playoff_reversed"] = len(old_playoff)

    # ---------------------------------------------------------------
    # 7) Delete old INJURY EVENTS for these games
    # ---------------------------------------------------------------
    try:
        del_result = conn.execute(sa_text(
            f"DELETE FROM player_injury_events WHERE gamelist_id IN ({ph})"
        ), gp)
        counts["injuries_deleted"] = del_result.rowcount
    except Exception:
        logger.debug("rollback_prior_results: injury event deletion failed (gamelist_id may not be populated)")
        counts["injuries_deleted"] = 0

    # ---------------------------------------------------------------
    # 8) Delete old per-game lines and substitutions
    # ---------------------------------------------------------------
    for table in ("game_batting_lines", "game_pitching_lines",
                  "game_substitutions"):
        try:
            conn.execute(sa_text(f"DELETE FROM {table} WHERE game_id IN ({ph})"), gp)
        except Exception:
            logger.exception("rollback_prior_results: failed to delete from %s", table)

    try:
        conn.execute(sa_text(f"DELETE FROM game_fielding_lines WHERE game_id IN ({ph})"), gp)
    except Exception:
        pass  # table may not exist yet

    logger.info(
        "rollback_prior_results: rolled back %d game(s): %s",
        len(resim_game_ids), counts,
    )
    return counts


# -------------------------------------------------------------------
# Public: weekly batch processing
# -------------------------------------------------------------------

def _process_level_subweek(
    level: int,
    games: List[Any],
    week_cache,
    subweek: str,
    league_year_id: int,
    season_week: int,
    game_constants: Dict[str, Any],
    level_configs: Dict[str, Any],
    rules_by_level: Dict[str, Dict[str, Any]],
    injury_types: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Process a single league level within a subweek.
    Runs in its own thread with its own DB connection.

    Returns dict with payloads, results, games, and counts.
    """
    from sqlalchemy import text as sa_text
    from services.game_engine_client import simulate_games_batch
    from services.stat_accumulator import (
        accumulate_subweek_stats_bulk,
        record_subweek_position_usage_bulk,
    )
    from services.rotation import advance_rotation_states_bulk
    from services.subweek_cache import load_subweek_state, SubweekCache

    engine = get_engine()

    with engine.connect() as level_conn:
        # Load mutable state for this subweek (uses shared week_cache)
        state = load_subweek_state(level_conn, week_cache, league_year_id, season_week)
        cache = SubweekCache.from_week_and_state(week_cache, state)

        # Pre-flight: halt immediately if any team's roster is depleted
        _check_roster_availability(cache, season_week, subweek, level)

        # Build payloads from cache (zero DB per game)
        payloads = []
        for game_row in games:
            game_id = int(game_row["id"])
            try:
                payload = build_game_payload_core_from_cache(
                    level_conn, cache, game_row, league_year_id, rules_by_level,
                )
                payloads.append(payload)
            except Exception as e:
                raise ValueError(
                    f"Failed to build game {game_id} (level {level}, subweek '{subweek}'): {e}"
                ) from e

        # Send to engine
        logger.info(
            "Sending %d games to engine for level %d, subweek '%s'",
            len(payloads), level, subweek,
        )
        results = simulate_games_batch(
            payloads, subweek,
            game_constants=game_constants,
            level_configs=level_configs,
            rules=rules_by_level,
            injury_types=injury_types,
            league_year_id=league_year_id,
            season_week=season_week,
            league_level=level,
        )
        logger.info(
            "Received %d results from engine for level %d, subweek '%s'",
            len(results), level, subweek,
        )

        # --- All post-engine writes in a single transaction ---

        # Engine diagnostic (isolated savepoint so a failure here cannot
        # poison the outer transaction with a PendingRollbackError)
        try:
            sent_ids = [p.get("game_id") for p in payloads]
            received_ids = set()
            for r in results:
                gid = r.get("game_id") or (r.get("result") or {}).get("game_id")
                if gid is not None:
                    received_ids.add(int(gid))
            missing_ids = [gid for gid in sent_ids if gid and int(gid) not in received_ids]
            with level_conn.begin_nested():
                level_conn.execute(sa_text("""
                    INSERT INTO engine_diagnostic_log
                        (league_year_id, season_week, subweek, league_level,
                         games_sent, results_received, missing_game_ids,
                         error_message)
                    VALUES
                        (:lyid, :sw, :sub, :ll,
                         :sent, :recv, :missing, :err)
                """), {
                    "lyid": league_year_id,
                    "sw": season_week,
                    "sub": subweek,
                    "ll": level,
                    "sent": len(payloads),
                    "recv": len(results),
                    "missing": json.dumps(missing_ids) if missing_ids else None,
                    "err": None,
                })
            if missing_ids:
                logger.warning(
                    "Engine diagnostic: %d missing game(s) for level %d, subweek '%s': %s",
                    len(missing_ids), level, subweek, missing_ids,
                )
        except Exception:
            logger.debug("Engine diagnostic logging failed (non-critical)")

        # --- Re-sim detection + rollback (BEFORE storing new results) ---
        all_game_ids = [
            int(p.get("game_id")) for p in payloads if p.get("game_id") is not None
        ]
        resim_game_ids = _detect_resim_games(level_conn, all_game_ids)
        is_resim = bool(resim_game_ids)

        if resim_game_ids:
            logger.info(
                "Re-sim detected for %d game(s) in level %d, subweek '%s': %s",
                len(resim_game_ids), level, subweek, resim_game_ids,
            )
            _rollback_prior_results(
                level_conn, resim_game_ids, league_year_id, season_week,
            )

        # Store game results
        result_count = _store_game_results_bulk(level_conn, results, payloads, games)

        # Update diagnostic with stored count
        try:
            with level_conn.begin_nested():
                level_conn.execute(sa_text("""
                    UPDATE engine_diagnostic_log
                    SET results_stored = :stored
                    WHERE league_year_id = :lyid AND season_week = :sw
                      AND subweek = :sub AND league_level = :ll
                    ORDER BY id DESC LIMIT 1
                """), {
                    "stored": result_count,
                    "lyid": league_year_id,
                    "sw": season_week,
                    "sub": subweek,
                    "ll": level,
                })
        except Exception:
            pass

        # Accumulate stats
        game_type_by_id = {}
        for g in games:
            gid = int(g["id"])
            gt = str((g.get("game_type") if isinstance(g, dict) else g["game_type"]) or "regular")
            game_type_by_id[gid] = gt

        stat_counts = accumulate_subweek_stats_bulk(
            level_conn, results, league_year_id,
            game_type_by_id=game_type_by_id,
            is_resim=is_resim,
        )

        # Position usage
        usage_count = record_subweek_position_usage_bulk(
            level_conn, payloads, league_year_id
        )

        # Stamina drain + injuries (NO recovery — that's global)
        drain_counts = _drain_stamina_and_persist_injuries(
            level_conn, results, league_year_id, injury_types=injury_types,
        )

        # Rotation advancement
        rot_count = advance_rotation_states_bulk(level_conn, payloads)

        # Playoff series tracking: update wins/losses and generate next games
        playoff_updates = _update_playoff_series_bulk(level_conn, results, payloads, games)

        # Single commit for all writes
        level_conn.commit()

        logger.info(
            "Level %d subweek '%s' complete: %d results, stats=%s, "
            "usage=%d, drain=%s, rotations=%d, playoff_updates=%d",
            level, subweek, result_count, stat_counts,
            usage_count, drain_counts, rot_count, len(playoff_updates),
        )

        return {
            "payloads": payloads,
            "results": results,
            "result_count": result_count,
            "stat_counts": stat_counts,
            "playoff_updates": playoff_updates,
        }


def build_week_payloads(
    conn,
    league_year_id: int,
    season_week: int,
    league_level: int | None = None,
    simulate: bool = True,
    subweek_filter: str | None = None,
) -> Dict[str, Any]:
    """
    Build game payloads for all games in a given season_week.

    Processes games sequentially by subweek (a -> b -> c -> d) to support
    state updates between subweeks.  Within each subweek, different league
    levels are processed in PARALLEL using ThreadPoolExecutor.

    If subweek_filter is set (e.g. "a"), only that single subweek is processed.

    After all levels complete for a subweek, global stamina recovery runs
    once (Option B — avoids double-recovery across levels).

    Args:
        conn: Database connection (used for initial queries and global recovery)
        league_year_id: The league year to filter games
        season_week: The week number to process
        league_level: Optional league level filter (e.g., 9 for MLB)
        simulate: If True, send payloads to game engine. If False, just build and return.

    Returns:
        {
            "league_year_id": 2026,
            "season_week": 1,
            "league_level": 9,
            "total_games": 47,
            "game_constants": {...},
            "level_configs": {"9": {...}},
            "rules": {"9": {...}},
            "injury_types": [...],
            "subweeks": {
                "a": [game_core_payload, ...],
                "b": [game_core_payload, ...],
                "c": [game_core_payload, ...],
                "d": [game_core_payload, ...]
            }
        }

    Raises:
        ValueError: If no games found or if any game fails to build
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.subweek_cache import load_week_cache, load_subweek_state, SubweekCache

    tables = _get_core_tables()
    gamelist = tables["gamelist"]
    seasons = tables["seasons"]
    league_years = tables["league_years"]

    # Resolve which season(s) map to this league_year_id
    ly_row = conn.execute(
        select(league_years.c.league_year).where(league_years.c.id == league_year_id)
    ).first()

    if not ly_row:
        raise ValueError(f"league_year_id {league_year_id} not found in league_years table")

    year = int(ly_row[0])

    season_rows = conn.execute(
        select(seasons.c.id).where(seasons.c.year == year)
    ).all()

    if not season_rows:
        raise ValueError(f"No seasons found for year {year}")

    season_ids = [int(row[0]) for row in season_rows]

    conditions = [
        gamelist.c.season.in_(season_ids),
        gamelist.c.season_week == season_week,
    ]

    if league_level is not None:
        conditions.append(gamelist.c.league_level == league_level)

    stmt = (
        select(gamelist)
        .where(and_(*conditions))
        .order_by(gamelist.c.season_subweek.asc(), gamelist.c.id.asc())
    )

    all_games = conn.execute(stmt).mappings().all()

    if not all_games:
        raise ValueError(
            f"No games found for league_year_id={league_year_id} (year={year}), "
            f"season_week={season_week}, league_level={league_level}"
        )

    # Load shared metadata (same for all subweeks and levels)
    game_constants = get_game_constants(conn)
    unique_levels = list(set(int(g["league_level"]) for g in all_games))
    level_configs_raw = get_level_configs_normalized_bulk(conn, unique_levels)
    level_configs = {str(k): v for k, v in level_configs_raw.items()}
    rules_by_level = {
        str(level): _get_level_rules_for_league(conn, level)
        for level in unique_levels
    }
    injury_types = get_all_injury_types(conn)

    # Collect ALL team IDs across the entire week for the WeekCache
    all_team_ids = set()
    for g in all_games:
        all_team_ids.add(int(g["home_team"]))
        all_team_ids.add(int(g["away_team"]))

    # Load WeekCache ONCE for the entire week (~10 queries)
    primary_level = league_level or int(all_games[0]["league_level"])
    week_cache = load_week_cache(
        conn,
        team_ids=list(all_team_ids),
        league_year_id=league_year_id,
        season_week=season_week,
        league_level_id=primary_level,
    )
    logger.info(
        "WeekCache loaded: %d teams, %d players",
        len(all_team_ids), len(week_cache.all_player_ids),
    )

    # Group games by subweek, then by level within each subweek
    games_by_subweek: Dict[str, Dict[int, List[Any]]] = {
        "a": {}, "b": {}, "c": {}, "d": {},
    }

    for game_row in all_games:
        subweek = str(game_row.get("season_subweek") or "a").lower()
        if subweek not in games_by_subweek:
            logger.warning(
                f"Game {game_row['id']} has unexpected subweek '{subweek}', "
                f"defaulting to 'a'"
            )
            subweek = "a"
        level = int(game_row["league_level"])
        games_by_subweek[subweek].setdefault(level, []).append(game_row)

    # Process each subweek in order (a -> b -> c -> d)
    subweek_payloads: Dict[str, List[Dict[str, Any]]] = {}
    total_games = 0

    subweeks_to_run = [subweek_filter] if subweek_filter else ["a", "b", "c", "d"]

    for subweek in subweeks_to_run:
        levels_games = games_by_subweek[subweek]

        if not levels_games:
            subweek_payloads[subweek] = []
            continue

        total_subweek_games = sum(len(g) for g in levels_games.values())
        logger.info(
            "Processing subweek '%s': %d games across %d level(s) "
            "(week %d, league_year %d)",
            subweek, total_subweek_games, len(levels_games),
            season_week, league_year_id,
        )

        sw_payloads = []

        if not simulate:
            # Non-simulation mode: just build payloads using main conn
            state = load_subweek_state(conn, week_cache, league_year_id, season_week)
            cache = SubweekCache.from_week_and_state(week_cache, state)

            for level, games in levels_games.items():
                for game_row in games:
                    game_id = int(game_row["id"])
                    try:
                        payload = build_game_payload_core_from_cache(
                            conn, cache, game_row, league_year_id, rules_by_level,
                        )
                        sw_payloads.append(payload)
                        total_games += 1
                    except Exception as e:
                        raise ValueError(
                            f"Failed to build game {game_id} in subweek '{subweek}': {e}"
                        ) from e

        else:
            # Simulation mode: parallel processing across levels
            levels = sorted(levels_games.keys())

            if len(levels) == 1:
                # Single level — no threading overhead needed
                level = levels[0]
                try:
                    level_result = _process_level_subweek(
                        level=level,
                        games=levels_games[level],
                        week_cache=week_cache,
                        subweek=subweek,
                        league_year_id=league_year_id,
                        season_week=season_week,
                        game_constants=game_constants,
                        level_configs=level_configs,
                        rules_by_level=rules_by_level,
                        injury_types=injury_types,
                    )
                    sw_payloads.extend(level_result["payloads"])
                    total_games += len(level_result["payloads"])
                except Exception as e:
                    raise ValueError(
                        f"Simulation failed for subweek '{subweek}': {e}"
                    ) from e
            else:
                # Multiple levels — run in parallel
                with ThreadPoolExecutor(
                    max_workers=min(len(levels), 6),
                    thread_name_prefix=f"sim-{subweek}",
                ) as pool:
                    futures = {}
                    for level in levels:
                        futures[pool.submit(
                            _process_level_subweek,
                            level=level,
                            games=levels_games[level],
                            week_cache=week_cache,
                            subweek=subweek,
                            league_year_id=league_year_id,
                            season_week=season_week,
                            game_constants=game_constants,
                            level_configs=level_configs,
                            rules_by_level=rules_by_level,
                            injury_types=injury_types,
                        )] = level

                    for future in as_completed(futures):
                        level = futures[future]
                        try:
                            level_result = future.result()
                            sw_payloads.extend(level_result["payloads"])
                            total_games += len(level_result["payloads"])
                        except Exception as e:
                            # Cancel remaining futures
                            for f in futures:
                                f.cancel()
                            raise ValueError(
                                f"Simulation failed for level {level}, "
                                f"subweek '{subweek}': {e}"
                            ) from e

            # GLOBAL: Stamina recovery runs ONCE after all levels drain
            try:
                recovery_count = _apply_global_stamina_recovery(
                    conn, league_year_id, league_level=league_level,
                )
                conn.commit()
                logger.info(
                    "Global stamina recovery for subweek '%s': %d players",
                    subweek, recovery_count,
                )
            except Exception as rec_err:
                logger.exception(
                    "Global stamina recovery failed for subweek '%s': %s",
                    subweek, rec_err,
                )
                try:
                    conn.rollback()
                except Exception:
                    pass

        subweek_payloads[subweek] = sw_payloads

    # Determine league level from first game if not provided
    detected_league_level = None
    if all_games:
        detected_league_level = all_games[0].get("league_level")

    return {
        "league_year_id": league_year_id,
        "season_week": season_week,
        "league_level": league_level or detected_league_level,
        "total_games": total_games,
        "game_constants": game_constants,
        "level_configs": level_configs,
        "rules": rules_by_level,
        "injury_types": injury_types,
        "subweeks": subweek_payloads,
    }


# -------------------------------------------------------------------
# Debug: synthetic matchup generator
# -------------------------------------------------------------------

def build_synthetic_matchups(
    conn,
    count: int = 10,
    league_level: int = 9,
    league_year_id: int | None = None,
    seed: int | None = None,
) -> Dict[str, Any]:
    """
    Generate synthetic game matchups for testing purposes.

    Creates N random team pairings using real team rosters and configurations.
    Returns the same payload structure as build_week_payloads() for engine
    compatibility.

    Args:
        conn: Database connection
        count: Number of games to generate (default: 10)
        league_level: League level to use (default: 9 for MLB)
        league_year_id: Optional league year ID. If not provided, uses the first
                        available league_years row.
        seed: Optional random seed for reproducibility

    Returns:
        {
            "league_year_id": 1,
            "season_week": 0,  # Synthetic games use week 0
            "league_level": 9,
            "total_games": 10,
            "game_constants": {...},
            "level_configs": {"9": {...}},
            "rules": {"9": {...}},
            "injury_types": [...],
            "subweeks": {
                "a": [game_payload, ...],
                "b": [],
                "c": [],
                "d": []
            }
        }
    """
    import random as rand_module

    rng = rand_module.Random(seed) if seed else rand_module.Random()

    tables = _get_core_tables()
    r_tables = _get_roster_tables()
    teams_table = r_tables["teams"]
    league_years = tables["league_years"]

    # Resolve league_year_id if not provided
    if league_year_id is None:
        ly_row = conn.execute(
            select(league_years.c.id)
            .order_by(league_years.c.league_year.desc())
            .limit(1)
        ).first()
        if not ly_row:
            raise ValueError("No league_years found in database")
        league_year_id = int(ly_row[0])

    # Get all teams at this league level
    team_rows = conn.execute(
        select(teams_table.c.id, teams_table.c.team_abbrev)
        .where(teams_table.c.team_level == league_level)
    ).all()

    if len(team_rows) < 2:
        raise ValueError(
            f"Need at least 2 teams at league_level={league_level}, "
            f"found {len(team_rows)}"
        )

    team_ids = [int(row[0]) for row in team_rows]

    logger.info(
        f"Building {count} synthetic matchups from {len(team_ids)} teams "
        f"at level {league_level}"
    )

    # Load static game constants
    game_constants = get_game_constants(conn)

    # Load level config and rules
    level_config = get_level_config_normalized(conn, league_level)
    level_configs = {str(league_level): level_config}

    rules = _get_level_rules_for_league(conn, league_level)
    rules_by_level = {str(league_level): rules}
    use_dh = bool(rules["dh"])

    # Load injury types
    injury_types = get_all_injury_types(conn)

    # Generate random matchups
    game_payloads: List[Dict[str, Any]] = []

    for game_idx in range(count):
        # Pick two different teams randomly
        home_team_id, away_team_id = rng.sample(team_ids, 2)

        # Generate a synthetic random seed for this game
        game_seed = rng.randint(1, 2**31 - 1)
        game_rng = rand_module.Random(game_seed)

        # Load ballpark for home team
        ballpark = get_ballpark_info(conn, home_team_id)

        # Pick starting pitchers
        try:
            home_rot = pick_starting_pitcher(conn, home_team_id, league_year_id)
            away_rot = pick_starting_pitcher(conn, away_team_id, league_year_id)
            home_sp_id = int(home_rot["starter_id"])
            away_sp_id = int(away_rot["starter_id"])
        except Exception as e:
            logger.warning(
                f"Skipping matchup {home_team_id} vs {away_team_id}: {e}"
            )
            continue

        # Get pitcher handedness for platoon matchups
        pitch_hands = _get_pitch_hands_bulk(conn, [away_sp_id, home_sp_id])
        away_sp_hand = pitch_hands.get(away_sp_id)
        home_sp_hand = pitch_hands.get(home_sp_id)

        home_vs_hand = away_sp_hand
        away_vs_hand = home_sp_hand

        # Build team sides
        try:
            home_side = build_team_game_side(
                conn=conn,
                team_id=home_team_id,
                league_level_id=league_level,
                league_year_id=league_year_id,
                season_week=0,  # Synthetic
                starter_id=home_sp_id,
                vs_hand=home_vs_hand,
                random_seed=game_seed,
                use_dh=use_dh,
            )
            away_side = build_team_game_side(
                conn=conn,
                team_id=away_team_id,
                league_level_id=league_level,
                league_year_id=league_year_id,
                season_week=0,
                starter_id=away_sp_id,
                vs_hand=away_vs_hand,
                random_seed=game_seed,
                use_dh=use_dh,
            )
        except Exception as e:
            logger.warning(
                f"Skipping matchup {home_team_id} vs {away_team_id}: {e}"
            )
            continue

        home_side["scheduled_rotation_slot"] = home_rot.get("scheduled_rotation_slot")
        away_side["scheduled_rotation_slot"] = away_rot.get("scheduled_rotation_slot")

        payload = {
            "game_id": -(game_idx + 1),  # Negative IDs for synthetic games
            "league_level_id": league_level,
            "league_year_id": league_year_id,
            "season_week": 0,
            "season_subweek": "a",
            "ballpark": ballpark,
            "home_side": home_side,
            "away_side": away_side,
            "random_seed": str(game_seed),
        }

        game_payloads.append(payload)

    logger.info(f"Generated {len(game_payloads)} synthetic game payloads")

    return {
        "league_year_id": league_year_id,
        "season_week": 0,
        "league_level": league_level,
        "total_games": len(game_payloads),
        "game_constants": game_constants,
        "level_configs": level_configs,
        "rules": rules_by_level,
        "injury_types": injury_types,
        "subweeks": {
            "a": game_payloads,
            "b": [],
            "c": [],
            "d": [],
        },
    }


def build_synthetic_matchups_with_progress(
    conn,
    count: int = 10,
    league_level: int = 9,
    league_year_id: int | None = None,
    seed: int | None = None,
    on_progress: callable = None,
) -> Dict[str, Any]:
    """
    Generate synthetic game matchups with progress callbacks.

    Same as build_synthetic_matchups but calls on_progress(current, total)
    after each game is built, allowing for progress tracking in background tasks.

    Args:
        conn: Database connection
        count: Number of games to generate
        league_level: League level to use (default: 9 for MLB)
        league_year_id: Optional league year ID
        seed: Optional random seed for reproducibility
        on_progress: Optional callback function(current: int, total: int)

    Returns:
        Same structure as build_synthetic_matchups()
    """
    import random as rand_module

    rng = rand_module.Random(seed) if seed else rand_module.Random()

    tables = _get_core_tables()
    r_tables = _get_roster_tables()
    teams_table = r_tables["teams"]
    league_years = tables["league_years"]

    # Resolve league_year_id if not provided
    if league_year_id is None:
        ly_row = conn.execute(
            select(league_years.c.id)
            .order_by(league_years.c.league_year.desc())
            .limit(1)
        ).first()
        if not ly_row:
            raise ValueError("No league_years found in database")
        league_year_id = int(ly_row[0])

    # Get all teams at this league level
    team_rows = conn.execute(
        select(teams_table.c.id, teams_table.c.team_abbrev)
        .where(teams_table.c.team_level == league_level)
    ).all()

    if len(team_rows) < 2:
        raise ValueError(
            f"Need at least 2 teams at league_level={league_level}, "
            f"found {len(team_rows)}"
        )

    team_ids = [int(row[0]) for row in team_rows]

    logger.info(
        f"Building {count} synthetic matchups from {len(team_ids)} teams "
        f"at level {league_level} (with progress tracking)"
    )

    # Load static game constants
    game_constants = get_game_constants(conn)

    # Load level config and rules
    level_config = get_level_config_normalized(conn, league_level)
    level_configs = {str(league_level): level_config}

    rules = _get_level_rules_for_league(conn, league_level)
    rules_by_level = {str(league_level): rules}
    use_dh = bool(rules["dh"])

    # Load injury types
    injury_types = get_all_injury_types(conn)

    # Generate random matchups
    game_payloads: List[Dict[str, Any]] = []
    games_attempted = 0

    for game_idx in range(count):
        games_attempted += 1

        # Pick two different teams randomly
        home_team_id, away_team_id = rng.sample(team_ids, 2)

        # Generate a synthetic random seed for this game
        game_seed = rng.randint(1, 2**31 - 1)

        # Load ballpark for home team
        ballpark = get_ballpark_info(conn, home_team_id)

        # Pick starting pitchers
        try:
            home_rot = pick_starting_pitcher(conn, home_team_id, league_year_id)
            away_rot = pick_starting_pitcher(conn, away_team_id, league_year_id)
            home_sp_id = int(home_rot["starter_id"])
            away_sp_id = int(away_rot["starter_id"])
        except Exception as e:
            logger.warning(
                f"Skipping matchup {home_team_id} vs {away_team_id}: {e}"
            )
            if on_progress:
                on_progress(games_attempted, count)
            continue

        # Get pitcher handedness for platoon matchups
        pitch_hands = _get_pitch_hands_bulk(conn, [away_sp_id, home_sp_id])
        away_sp_hand = pitch_hands.get(away_sp_id)
        home_sp_hand = pitch_hands.get(home_sp_id)

        home_vs_hand = away_sp_hand
        away_vs_hand = home_sp_hand

        # Build team sides
        try:
            home_side = build_team_game_side(
                conn=conn,
                team_id=home_team_id,
                league_level_id=league_level,
                league_year_id=league_year_id,
                season_week=0,
                starter_id=home_sp_id,
                vs_hand=home_vs_hand,
                random_seed=game_seed,
                use_dh=use_dh,
            )
            away_side = build_team_game_side(
                conn=conn,
                team_id=away_team_id,
                league_level_id=league_level,
                league_year_id=league_year_id,
                season_week=0,
                starter_id=away_sp_id,
                vs_hand=away_vs_hand,
                random_seed=game_seed,
                use_dh=use_dh,
            )
        except Exception as e:
            logger.warning(
                f"Skipping matchup {home_team_id} vs {away_team_id}: {e}"
            )
            if on_progress:
                on_progress(games_attempted, count)
            continue

        home_side["scheduled_rotation_slot"] = home_rot.get("scheduled_rotation_slot")
        away_side["scheduled_rotation_slot"] = away_rot.get("scheduled_rotation_slot")

        payload = {
            "game_id": -(game_idx + 1),
            "league_level_id": league_level,
            "league_year_id": league_year_id,
            "season_week": 0,
            "season_subweek": "a",
            "ballpark": ballpark,
            "home_side": home_side,
            "away_side": away_side,
            "random_seed": str(game_seed),
        }

        game_payloads.append(payload)

        # Report progress
        if on_progress:
            on_progress(games_attempted, count)

    logger.info(f"Generated {len(game_payloads)} synthetic game payloads")

    return {
        "league_year_id": league_year_id,
        "season_week": 0,
        "league_level": league_level,
        "total_games": len(game_payloads),
        "game_constants": game_constants,
        "level_configs": level_configs,
        "rules": rules_by_level,
        "injury_types": injury_types,
        "subweeks": {
            "a": game_payloads,
            "b": [],
            "c": [],
            "d": [],
        },
    }