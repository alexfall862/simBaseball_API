# services/game_payload.py

from dataclasses import dataclass
from typing import Dict, Any, List

import json
import logging

from sqlalchemy import MetaData, Table, select, and_

logger = logging.getLogger(__name__)

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


class _DummyRow:
    """
    Lightweight stand-in so _compute_derived_raw_ratings can work with a dict
    instead of a real Row object.
    """
    def __init__(self, mapping: Dict[str, Any]):
        self._mapping = mapping


def _build_engine_player_view_from_mapping(mapping: Dict[str, Any]) -> Dict[str, Any]:
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
    derived = _compute_derived_raw_ratings(dummy_row) or {}

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

    gamelist = Table("gamelist", md, autoload_with=engine)
    seasons = Table("seasons", md, autoload_with=engine)
    league_years = Table("league_years", md, autoload_with=engine)
    level_rules = Table("level_rules", md, autoload_with=engine)
    level_sim_config = Table("level_sim_config", md, autoload_with=engine)
    teams = Table("teams", md, autoload_with=engine)
    player_strategies = Table("playerStrategies", md, autoload_with=engine)

    _CORE_METADATA = md
    _CORE_TABLES = {
        "gamelist": gamelist,
        "seasons": seasons,
        "league_years": league_years,
        "level_rules": level_rules,
        "level_sim_config": level_sim_config,
        "teams": teams,
        "playerStrategies": player_strategies,
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

        strat = {
            "plate_approach": row.get("plate_approach") or DEFAULT_PLAYER_STRATEGY["plate_approach"],
            "pitching_approach": row.get("pitching_approach") or DEFAULT_PLAYER_STRATEGY["pitching_approach"],
            "baserunning_approach": row.get("baserunning_approach") or DEFAULT_PLAYER_STRATEGY["baserunning_approach"],
            "usage_preference": row.get("usage_preference") or DEFAULT_PLAYER_STRATEGY["usage_preference"],
        }
        out[pid] = strat

    return out

def _load_player_strategy(conn, player_id: int, org_id: int | None = None) -> Dict[str, str]:
    """
    Load per-player strategy for the given player/org, if present.
    Defaults all strategy fields to 'normal' if not set.
    """
    tables = _get_core_tables()
    strategies = tables["playerStrategies"]

    conditions = [strategies.c.playerID == player_id]
    if org_id is not None and hasattr(strategies.c, "orgID"):
        conditions.append(strategies.c.orgID == org_id)

    stmt = select(strategies).where(and_(*conditions)).limit(1)
    row = conn.execute(stmt).mappings().first()

    if not row:
        return {
            "plate_approach": "normal",
            "pitching_approach": "normal",
            "baserunning_approach": "normal",
            "usage_preference": "normal",
        }

    return {
        "plate_approach": row.get("plate_approach") or "normal",
        "pitching_approach": row.get("pitching_approach") or "normal",
        "baserunning_approach": row.get("baserunning_approach") or "normal",
        "usage_preference": row.get("usage_preference") or "normal",
    }


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

    # Apply injury maluses to *_base attributes
    malus = get_active_injury_malus(conn, player_id)
    adjusted_mapping = dict(raw_mapping)

    for attr, delta in malus.items():
        if attr.endswith("_base") and attr in adjusted_mapping:
            base_val = adjusted_mapping.get(attr)
            try:
                base_num = float(base_val) if base_val is not None else 0.0
            except (TypeError, ValueError):
                base_num = 0.0
            try:
                delta_num = float(delta)
            except (TypeError, ValueError):
                delta_num = 0.0
            adjusted_mapping[attr] = base_num + delta_num

    engine_player = _build_engine_player_view_from_mapping(adjusted_mapping)
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

    # 2) Bulk-load injury maluses for all players
    malus_by_player = get_active_injury_malus_bulk(conn, ids)

    for pid in ids:
        raw_mapping = raw_by_id.get(pid)
        if raw_mapping is None:
            continue

        adjusted_mapping = dict(raw_mapping)
        malus = malus_by_player.get(pid) or {}

        for attr, delta in malus.items():
            if attr.endswith("_base") and attr in adjusted_mapping:
                base_val = adjusted_mapping.get(attr)
                try:
                    base_num = float(base_val) if base_val is not None else 0.0
                except (TypeError, ValueError):
                    base_num = 0.0
                try:
                    delta_num = float(delta)
                except (TypeError, ValueError):
                    delta_num = 0.0
                adjusted_mapping[attr] = base_num + delta_num

        engine_player = _build_engine_player_view_from_mapping(adjusted_mapping)
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
        select(teams.c.orgID).where(teams.c.id == team_id).limit(1)
    ).first()
    if not team_row:
        raise ValueError(f"Team id {team_id} not found")

    org_id = int(team_row[0])

    player_ids = _get_team_roster_player_ids(conn, team_id)
    players_by_id: Dict[int, Dict[str, Any]] = {}


    if not player_ids:
        # No players; return an empty shell
        return {
            "team_id": team_id,
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

        # Stamina
        ep["stamina"] = int(stamina_by_player.get(pid, 100))

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

    # 2) We are given the starting pitcher for this team
    # 3) Available pitchers: all pitchers except starter
    available_pitcher_ids: List[int] = [
        pid for pid, pdata in players_by_id.items()
        if (pdata.get("ptype") or "").lower() == "pitcher" and pid != starter_id
    ]

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
        "org_id": org_id,
        "players": list(players_by_id.values()),
        "starting_pitcher_id": starter_id,
        "available_pitcher_ids": available_pitcher_ids,
        "defense": defense,
        "lineup": lineup_ids,
        "bench": bench_ids,
        "pregame_injuries": pregame_injuries,
    }

# -------------------------------------------------------------------
# Public: full game payload
# -------------------------------------------------------------------

def build_game_payload(conn, game_id: int) -> Dict[str, Any]:
    """
    Build the full engine payload for a single game_id.

    - Looks up the game in gamelist
    - Resolves league_year_id via seasons/league_years
    - Loads game rules from level_rules (including DH flag)
    - Picks starting pitchers for home and away
    - Derives vs_hand for each lineup from the opponent SP's pitch_hand
    - Rolls pregame injuries (if random_seed is set)
    - Builds team-side payloads
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

    # Load game rules for this league level
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

    payload: Dict[str, Any] = {
        "game_id": game_id,
        "league_level_id": league_level_id,
        "league_year_id": league_year_id,
        "season_week": season_week,
        "season_subweek": season_subweek,
        "rules": rules,
        "ballpark": ballpark,
        "home_side": home_side,
        "away_side": away_side,
    }

    if random_seed is not None:
        payload["random_seed"] = str(random_seed)

    return payload


# -------------------------------------------------------------------
# Public: weekly batch processing
# -------------------------------------------------------------------

def build_week_payloads(
    conn,
    league_year_id: int,
    season_week: int,
    league_level: int | None = None,
) -> Dict[str, Any]:
    """
    Build game payloads for all games in a given season_week.

    Processes games sequentially by subweek (a → b → c → d) to allow
    for state updates (stamina, rotation, injuries) between subweeks.

    Args:
        conn: Database connection
        league_year_id: The league year to filter games
        season_week: The week number to process
        league_level: Optional league level filter (e.g., 9 for MLB)

    Returns:
        {
            "league_year_id": 2026,
            "season_week": 1,
            "league_level": 9,
            "total_games": 47,
            "subweeks": {
                "a": [game_payload, ...],
                "b": [game_payload, ...],
                "c": [game_payload, ...],
                "d": [game_payload, ...]
            }
        }

    Raises:
        ValueError: If no games found or if any game fails to build
    """
    tables = _get_core_tables()
    gamelist = tables["gamelist"]
    seasons = tables["seasons"]
    league_years = tables["league_years"]

    # Resolve which season(s) map to this league_year_id
    # league_years.id -> league_years.league_year (year) -> seasons.year -> seasons.id
    ly_row = conn.execute(
        select(league_years.c.league_year).where(league_years.c.id == league_year_id)
    ).first()

    if not ly_row:
        raise ValueError(f"league_year_id {league_year_id} not found in league_years table")

    year = int(ly_row[0])

    # Find season(s) for this year
    season_rows = conn.execute(
        select(seasons.c.id).where(seasons.c.year == year)
    ).all()

    if not season_rows:
        raise ValueError(f"No seasons found for year {year}")

    season_ids = [int(row[0]) for row in season_rows]

    # Build query conditions (gamelist.season column contains season_id)
    conditions = [
        gamelist.c.season.in_(season_ids),
        gamelist.c.season_week == season_week,
    ]

    if league_level is not None:
        conditions.append(gamelist.c.league_level == league_level)

    # Load all games for this week
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

    # Group games by subweek
    games_by_subweek: Dict[str, List[Any]] = {"a": [], "b": [], "c": [], "d": []}

    for game_row in all_games:
        subweek = game_row.get("season_subweek") or "a"
        subweek = str(subweek).lower()

        if subweek not in games_by_subweek:
            logger.warning(
                f"Game {game_row['id']} has unexpected subweek '{subweek}', "
                f"defaulting to 'a'"
            )
            subweek = "a"

        games_by_subweek[subweek].append(game_row)

    # Process each subweek in order
    subweek_payloads: Dict[str, List[Dict[str, Any]]] = {}
    total_games = 0

    for subweek in ["a", "b", "c", "d"]:
        games = games_by_subweek[subweek]

        if not games:
            subweek_payloads[subweek] = []
            continue

        logger.info(
            f"Processing subweek '{subweek}': {len(games)} games "
            f"(week {season_week}, league_year {league_year_id})"
        )

        payloads = []

        for game_row in games:
            game_id = int(game_row["id"])

            try:
                payload = build_game_payload(conn, game_id)
                payloads.append(payload)
                total_games += 1

            except Exception as e:
                logger.error(
                    f"Failed to build payload for game_id={game_id} "
                    f"in subweek '{subweek}': {e}"
                )
                raise ValueError(
                    f"Failed to build game {game_id} in subweek '{subweek}': {e}"
                ) from e

        subweek_payloads[subweek] = payloads

        # Send payloads to game engine for simulation
        try:
            from services.game_engine_client import simulate_games_batch

            logger.info(
                f"Sending {len(payloads)} games to engine for subweek '{subweek}'"
            )

            # Call game engine to simulate this subweek's games
            results = simulate_games_batch(payloads, subweek)

            logger.info(
                f"Received {len(results)} results from engine for subweek '{subweek}'"
            )

            # Store game results in database
            # TODO: Implement result storage
            # _store_game_results(conn, results)

            # Update player state for next subweek
            # TODO: Implement state updates
            # _update_player_state_after_subweek(conn, results, league_year_id)

        except ImportError:
            # Game engine client not available - skip simulation
            logger.warning(
                f"Game engine client not available, skipping simulation "
                f"for subweek '{subweek}'"
            )

        except Exception as e:
            logger.error(f"Failed to simulate subweek '{subweek}': {e}")
            # Depending on your requirements, you can either:
            # - Raise to abort the entire week
            # - Continue to next subweek (comment out the raise below)
            raise ValueError(
                f"Simulation failed for subweek '{subweek}': {e}"
            ) from e

    # Determine league level from first game if not provided
    detected_league_level = None
    if all_games:
        detected_league_level = all_games[0].get("league_level")

    return {
        "league_year_id": league_year_id,
        "season_week": season_week,
        "league_level": league_level or detected_league_level,
        "total_games": total_games,
        "subweeks": subweek_payloads,
    }