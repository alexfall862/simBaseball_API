# services/subweek_cache.py
"""
Pre-loads ALL data needed for a subweek's games in ~12-14 bulk queries,
replacing thousands of per-game/per-team queries.

Usage:
    cache = load_subweek_cache(conn, team_ids, league_year_id, season_week, league_level_id)
    # Then assemble payloads from cache without touching the DB.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from sqlalchemy import select, and_

logger = logging.getLogger("app")


@dataclass
class SubweekCache:
    """In-memory snapshot of everything needed to build game payloads."""

    # --- Team-level ---
    # team_id -> {orgID, team_abbrev, team_name, team_nickname,
    #             ballpark_name, pitch_break_mod, power_mod}
    team_meta: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # team_id -> [player_id, ...]
    roster_by_team: Dict[int, List[int]] = field(default_factory=dict)

    # team_id -> org_id
    org_by_team: Dict[int, int] = field(default_factory=dict)

    # team_id -> strategy dict (or defaults)
    team_strategy_by_team: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # team_id -> [{slot, player_id, role}, ...]
    bullpen_order_by_team: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)

    # --- Rotation ---
    # team_id -> rotation row dict or None
    rotation_by_team: Dict[int, Any] = field(default_factory=dict)

    # rotation_id -> [slot row dicts]
    rotation_slots_by_rotation: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)

    # team_id -> state row dict or None
    rotation_state_by_team: Dict[int, Any] = field(default_factory=dict)

    # --- Lineup / Defense ---
    # team_id -> {position_code: [plan row dicts]}
    position_plans_by_team: Dict[int, Dict[str, List[Dict]]] = field(default_factory=dict)

    # team_id -> {position_code: ({player_id: starts}, total_starts)}
    weekly_usage_by_team: Dict[int, Dict[str, Tuple]] = field(default_factory=dict)

    # team_id -> {slot: role_row}
    lineup_roles_by_team: Dict[int, Dict[int, Dict]] = field(default_factory=dict)

    # --- Player-level (all players across all teams) ---
    # player_id -> raw simbbPlayers row dict
    player_rows: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # player_id -> {attr: delta} from injury malus
    injury_malus: Dict[int, Dict[str, float]] = field(default_factory=dict)

    # player_id -> engine player view (with injuries applied, derived ratings computed)
    engine_views: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # player_id -> stamina int (0-100)
    stamina: Dict[int, int] = field(default_factory=dict)

    # Raw strategy rows from playerStrategies for all players
    strategy_rows_by_player: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)

    # player_id -> {position_code: xp_mod float}
    xp_mods: Dict[int, Dict[str, float]] = field(default_factory=dict)

    # player_id -> pitch_hand ('L', 'R', or None)
    pitch_hands: Dict[int, str] = field(default_factory=dict)

    # Position weights from rating_config (or None)
    position_weights: Any = None

    # All player IDs across all teams
    all_player_ids: Set[int] = field(default_factory=set)

    # pitcher IDs per team (for fallback rotation)
    pitcher_ids_by_team: Dict[int, List[int]] = field(default_factory=dict)


def load_subweek_cache(
    conn,
    team_ids: List[int],
    league_year_id: int,
    season_week: int,
    league_level_id: int,
) -> SubweekCache:
    """
    Execute ~12-14 bulk queries and return a fully populated SubweekCache.
    """
    from services.game_payload import (
        _get_core_tables,
        _get_roster_tables,
        _build_engine_player_view_from_mapping,
        _load_position_weights,
        DEFAULT_PLAYER_STRATEGY,
    )
    from services.injuries import get_active_injury_malus_bulk
    from services.stamina import get_effective_stamina_bulk
    from services.defense_xp import compute_defensive_xp_mod_for_players

    cache = SubweekCache()
    unique_team_ids = list(set(int(t) for t in team_ids))

    if not unique_team_ids:
        return cache

    r_tables = _get_roster_tables()
    c_tables = _get_core_tables()
    contracts = r_tables["contracts"]
    details = r_tables["contract_details"]
    shares = r_tables["contract_team_share"]
    orgs = r_tables["organizations"]
    players = r_tables["players"]
    levels = r_tables["levels"]
    teams = r_tables["teams"]

    # ---------------------------------------------------------------
    # 1) Team meta (ballpark info included)
    # ---------------------------------------------------------------
    team_rows = conn.execute(
        select(
            teams.c.id,
            teams.c.orgID,
            teams.c.team_abbrev,
            teams.c.team_name,
            teams.c.team_nickname,
            teams.c.ballpark_name,
            teams.c.pitch_break_mod,
            teams.c.power_mod,
        ).where(teams.c.id.in_(unique_team_ids))
    ).mappings().all()

    for row in team_rows:
        tid = int(row["id"])
        cache.team_meta[tid] = dict(row)
        cache.org_by_team[tid] = int(row["orgID"])

    # ---------------------------------------------------------------
    # 2) Rosters: all player IDs per team (single bulk query)
    # ---------------------------------------------------------------
    roster_stmt = (
        select(
            teams.c.id.label("team_id"),
            players.c.id.label("player_id"),
            players.c.ptype,
        )
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
        .where(
            and_(
                contracts.c.isActive == 1,
                shares.c.isHolder == 1,
                teams.c.id.in_(unique_team_ids),
            )
        )
    )

    for row in conn.execute(roster_stmt).mappings():
        tid = int(row["team_id"])
        pid = int(row["player_id"])
        ptype = (row.get("ptype") or "").lower()

        cache.roster_by_team.setdefault(tid, []).append(pid)
        cache.all_player_ids.add(pid)

        if ptype == "pitcher":
            cache.pitcher_ids_by_team.setdefault(tid, []).append(pid)

    all_pids = list(cache.all_player_ids)
    if not all_pids:
        return cache

    logger.info(
        "subweek_cache: %d teams, %d players — loading bulk data",
        len(unique_team_ids), len(all_pids),
    )

    # ---------------------------------------------------------------
    # 3) All simbbPlayers rows
    # ---------------------------------------------------------------
    player_rows = conn.execute(
        select(players).where(players.c.id.in_(all_pids))
    ).mappings().all()

    for row in player_rows:
        pid = int(row["id"])
        cache.player_rows[pid] = dict(row)

        # Extract pitch hand while we have the data
        raw_hand = row.get("pitch_hand")
        if raw_hand:
            s = str(raw_hand).strip().upper()
            if s and s[0] in ("L", "R"):
                cache.pitch_hands[pid] = s[0]

    # ---------------------------------------------------------------
    # 4) Injury maluses (bulk — internally queries 3 tables)
    # ---------------------------------------------------------------
    cache.injury_malus = get_active_injury_malus_bulk(conn, all_pids)

    # ---------------------------------------------------------------
    # 5) Position weights + engine player views (with injuries applied)
    # ---------------------------------------------------------------
    cache.position_weights = _load_position_weights(conn)

    for pid in all_pids:
        raw_mapping = cache.player_rows.get(pid)
        if raw_mapping is None:
            continue

        adjusted = dict(raw_mapping)
        malus = cache.injury_malus.get(pid) or {}
        for attr, delta in malus.items():
            if attr.endswith("_base") and attr in adjusted:
                base_val = adjusted.get(attr)
                try:
                    base_num = float(base_val) if base_val is not None else 0.0
                except (TypeError, ValueError):
                    base_num = 0.0
                try:
                    delta_num = float(delta)
                except (TypeError, ValueError):
                    delta_num = 0.0
                adjusted[attr] = base_num + delta_num

        cache.engine_views[pid] = _build_engine_player_view_from_mapping(
            adjusted, cache.position_weights
        )

    # ---------------------------------------------------------------
    # 6) Stamina (bulk — single query)
    # ---------------------------------------------------------------
    cache.stamina = get_effective_stamina_bulk(conn, all_pids, league_year_id)

    # ---------------------------------------------------------------
    # 7) Defensive XP mods (bulk — 2 queries)
    # ---------------------------------------------------------------
    cache.xp_mods = compute_defensive_xp_mod_for_players(
        conn, all_pids, league_level_id
    )

    # ---------------------------------------------------------------
    # 8) Player strategies (bulk — single query, org filtering at assembly)
    # ---------------------------------------------------------------
    strategies_table = c_tables["playerStrategies"]
    strat_rows = list(
        conn.execute(
            select(strategies_table).where(
                strategies_table.c.playerID.in_(all_pids)
            )
        ).mappings()
    )

    for row in strat_rows:
        pid = int(row["playerID"])
        cache.strategy_rows_by_player.setdefault(pid, []).append(dict(row))

    # ---------------------------------------------------------------
    # 9) Team strategies (bulk — single query)
    # ---------------------------------------------------------------
    _load_team_strategies_bulk(conn, c_tables, unique_team_ids, cache)

    # ---------------------------------------------------------------
    # 10) Bullpen orders (bulk — single query)
    # ---------------------------------------------------------------
    _load_bullpen_orders_bulk(conn, c_tables, unique_team_ids, cache)

    # ---------------------------------------------------------------
    # 11) Rotation data (3 queries)
    # ---------------------------------------------------------------
    _load_rotations_bulk(conn, unique_team_ids, cache)

    # ---------------------------------------------------------------
    # 12) Position plans (bulk — single query)
    # ---------------------------------------------------------------
    _load_position_plans_bulk(conn, c_tables, unique_team_ids, cache)

    # ---------------------------------------------------------------
    # 13) Weekly usage (bulk — single query)
    # ---------------------------------------------------------------
    _load_weekly_usage_bulk(conn, c_tables, unique_team_ids, league_year_id, season_week, cache)

    # ---------------------------------------------------------------
    # 14) Lineup roles (bulk — single query)
    # ---------------------------------------------------------------
    _load_lineup_roles_bulk(conn, c_tables, unique_team_ids, cache)

    logger.info("subweek_cache: fully loaded")
    return cache


# -------------------------------------------------------------------
# Internal bulk loaders
# -------------------------------------------------------------------

def _load_team_strategies_bulk(conn, tables, team_ids, cache: SubweekCache):
    """Bulk load team_strategy for all teams."""
    from services.game_payload import _DEFAULT_TEAM_STRATEGY

    ts = tables.get("team_strategy")
    if ts is None:
        from sqlalchemy import Table, MetaData
        meta = MetaData()
        meta.reflect(bind=conn, only=["team_strategy"])
        ts = meta.tables.get("team_strategy")
        if ts is None:
            for tid in team_ids:
                cache.team_strategy_by_team[tid] = {
                    **_DEFAULT_TEAM_STRATEGY, "team_id": tid
                }
            return

    rows = conn.execute(
        select(ts).where(ts.c.team_id.in_(team_ids))
    ).mappings().all()

    found = set()
    for row in rows:
        tid = int(row["team_id"])
        found.add(tid)
        strat = dict(row)
        # Parse intentional_walk_list from JSON if needed
        iwl = strat.get("intentional_walk_list")
        if isinstance(iwl, str):
            try:
                strat["intentional_walk_list"] = json.loads(iwl)
            except (TypeError, json.JSONDecodeError):
                strat["intentional_walk_list"] = []
        elif iwl is None:
            strat["intentional_walk_list"] = []
        cache.team_strategy_by_team[tid] = strat

    for tid in team_ids:
        if tid not in found:
            cache.team_strategy_by_team[tid] = {
                **_DEFAULT_TEAM_STRATEGY, "team_id": tid
            }


def _load_bullpen_orders_bulk(conn, tables, team_ids, cache: SubweekCache):
    """Bulk load team_bullpen_order for all teams."""
    tbo = tables.get("team_bullpen_order")
    if tbo is None:
        from sqlalchemy import Table, MetaData
        meta = MetaData()
        meta.reflect(bind=conn, only=["team_bullpen_order"])
        tbo = meta.tables.get("team_bullpen_order")
        if tbo is None:
            for tid in team_ids:
                cache.bullpen_order_by_team[tid] = []
            return

    rows = conn.execute(
        select(tbo).where(tbo.c.team_id.in_(team_ids)).order_by(
            tbo.c.team_id.asc(), tbo.c.slot.asc()
        )
    ).mappings().all()

    for tid in team_ids:
        cache.bullpen_order_by_team[tid] = []

    for row in rows:
        tid = int(row["team_id"])
        cache.bullpen_order_by_team.setdefault(tid, []).append({
            "slot": int(row["slot"]),
            "player_id": int(row["player_id"]),
            "role": row.get("role"),
        })


def _load_rotations_bulk(conn, team_ids, cache: SubweekCache):
    """Bulk load rotation config, slots, and state for all teams."""
    from services.rotation import _get_rotation_tables

    r_tables = _get_rotation_tables()
    rotation = r_tables["rotation"]
    slots = r_tables["slots"]
    state = r_tables["state"]

    # Rotation config
    rot_rows = conn.execute(
        select(rotation).where(rotation.c.team_id.in_(team_ids))
    ).mappings().all()

    rotation_ids = []
    for row in rot_rows:
        tid = int(row["team_id"])
        cache.rotation_by_team[tid] = dict(row)
        rotation_ids.append(int(row["id"]))

    # Rotation slots
    if rotation_ids:
        slot_rows = conn.execute(
            select(slots).where(slots.c.rotation_id.in_(rotation_ids)).order_by(
                slots.c.rotation_id.asc(), slots.c.slot.asc()
            )
        ).mappings().all()

        for row in slot_rows:
            rid = int(row["rotation_id"])
            cache.rotation_slots_by_rotation.setdefault(rid, []).append(dict(row))

    # Rotation state
    state_rows = conn.execute(
        select(state).where(state.c.team_id.in_(team_ids))
    ).mappings().all()

    for row in state_rows:
        tid = int(row["team_id"])
        cache.rotation_state_by_team[tid] = dict(row)


def _load_position_plans_bulk(conn, tables, team_ids, cache: SubweekCache):
    """Bulk load team_position_plan for all teams."""
    tpp = tables.get("team_position_plan")
    if tpp is None:
        from sqlalchemy import Table, MetaData
        meta = MetaData()
        meta.reflect(bind=conn, only=["team_position_plan"])
        tpp = meta.tables.get("team_position_plan")
        if tpp is None:
            return

    rows = conn.execute(
        select(tpp).where(tpp.c.team_id.in_(team_ids)).order_by(
            tpp.c.team_id.asc(),
            tpp.c.position_code.asc(),
            tpp.c.priority.asc(),
        )
    ).mappings().all()

    for tid in team_ids:
        cache.position_plans_by_team[tid] = {}

    for row in rows:
        tid = int(row["team_id"])
        pos = row["position_code"]
        cache.position_plans_by_team.setdefault(tid, {}).setdefault(pos, []).append(dict(row))


def _load_weekly_usage_bulk(conn, tables, team_ids, league_year_id, season_week, cache: SubweekCache):
    """Bulk load player_position_usage_week for all teams."""
    ppuw = tables.get("player_position_usage_week")
    if ppuw is None:
        from sqlalchemy import Table, MetaData
        meta = MetaData()
        meta.reflect(bind=conn, only=["player_position_usage_week"])
        ppuw = meta.tables.get("player_position_usage_week")
        if ppuw is None:
            return

    rows = conn.execute(
        select(ppuw).where(
            and_(
                ppuw.c.league_year_id == league_year_id,
                ppuw.c.season_week == season_week,
                ppuw.c.team_id.in_(team_ids),
            )
        )
    ).mappings().all()

    for tid in team_ids:
        cache.weekly_usage_by_team[tid] = {}

    for row in rows:
        tid = int(row["team_id"])
        pos = row["position_code"]
        pid = int(row["player_id"])
        starts = int(row.get("starts_this_week") or row.get("starts", 0))

        team_usage = cache.weekly_usage_by_team.setdefault(tid, {})
        if pos not in team_usage:
            team_usage[pos] = ({}, 0)

        usage_map, total = team_usage[pos]
        usage_map[pid] = usage_map.get(pid, 0) + starts
        team_usage[pos] = (usage_map, total + starts)


def _load_lineup_roles_bulk(conn, tables, team_ids, cache: SubweekCache):
    """Bulk load team_lineup_roles for all teams."""
    tlr = tables.get("team_lineup_roles")
    if tlr is None:
        from sqlalchemy import Table, MetaData
        meta = MetaData()
        meta.reflect(bind=conn, only=["team_lineup_roles"])
        tlr = meta.tables.get("team_lineup_roles")
        if tlr is None:
            return

    rows = conn.execute(
        select(tlr).where(tlr.c.team_id.in_(team_ids)).order_by(
            tlr.c.team_id.asc(), tlr.c.slot.asc()
        )
    ).mappings().all()

    for tid in team_ids:
        cache.lineup_roles_by_team[tid] = {}

    for row in rows:
        tid = int(row["team_id"])
        slot = int(row["slot"])
        cache.lineup_roles_by_team.setdefault(tid, {})[slot] = dict(row)


# -------------------------------------------------------------------
# Strategy resolution helper (mirrors _load_player_strategies_bulk)
# -------------------------------------------------------------------

def resolve_strategies_for_team(
    cache: SubweekCache,
    player_ids: List[int],
    org_id: int,
) -> Dict[int, Dict[str, Any]]:
    """
    Resolve player strategies for a specific team from cached raw rows.
    Mirrors the org-preference logic in _load_player_strategies_bulk.
    """
    from services.game_payload import DEFAULT_PLAYER_STRATEGY

    out: Dict[int, Dict[str, Any]] = {}

    for pid in player_ids:
        rows = cache.strategy_rows_by_player.get(pid)
        if not rows:
            out[pid] = DEFAULT_PLAYER_STRATEGY.copy()
            continue

        # Pick best row: prefer matching org
        best = None
        for row in rows:
            row_org = row.get("orgID")
            if row_org == org_id:
                best = row
                break
            if best is None:
                best = row

        if best is None:
            out[pid] = DEFAULT_PLAYER_STRATEGY.copy()
            continue

        strat = {
            "plate_approach": best.get("plate_approach") or DEFAULT_PLAYER_STRATEGY["plate_approach"],
            "pitching_approach": best.get("pitching_approach") or DEFAULT_PLAYER_STRATEGY["pitching_approach"],
            "baserunning_approach": best.get("baserunning_approach") or DEFAULT_PLAYER_STRATEGY["baserunning_approach"],
            "usage_preference": best.get("usage_preference") or DEFAULT_PLAYER_STRATEGY["usage_preference"],
        }

        stealfreq = best.get("stealfreq")
        strat["stealfreq"] = float(stealfreq) if stealfreq is not None else DEFAULT_PLAYER_STRATEGY["stealfreq"]

        pickofffreq = best.get("pickofffreq")
        strat["pickofffreq"] = float(pickofffreq) if pickofffreq is not None else DEFAULT_PLAYER_STRATEGY["pickofffreq"]

        pitchchoices_raw = best.get("pitchchoices")
        if pitchchoices_raw is None:
            strat["pitchchoices"] = DEFAULT_PLAYER_STRATEGY["pitchchoices"].copy()
        elif isinstance(pitchchoices_raw, list):
            strat["pitchchoices"] = pitchchoices_raw
        else:
            try:
                strat["pitchchoices"] = json.loads(pitchchoices_raw)
            except (TypeError, json.JSONDecodeError):
                strat["pitchchoices"] = DEFAULT_PLAYER_STRATEGY["pitchchoices"].copy()

        pitchpull = best.get("pitchpull")
        strat["pitchpull"] = int(pitchpull) if pitchpull is not None else None

        pulltend = best.get("pulltend")
        strat["pulltend"] = pulltend if pulltend else None

        out[pid] = strat

    return out
