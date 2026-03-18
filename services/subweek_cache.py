# services/subweek_cache.py
"""
Pre-loads ALL data needed for a subweek's games in bulk queries,
replacing thousands of per-game/per-team queries.

Architecture: WeekCache (static, loaded once) + SubweekState (mutable, reloaded
per subweek).  SubweekCache is the combined view used by payload builders.

Usage:
    week_cache = load_week_cache(conn, team_ids, league_year_id, season_week, league_level_id)
    # Then for each subweek:
    state = load_subweek_state(conn, week_cache, league_year_id)
    cache = SubweekCache.from_week_and_state(week_cache, state)
    # Assemble payloads from cache without touching the DB.
"""

import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from sqlalchemy import select, and_

logger = logging.getLogger("app")


# -------------------------------------------------------------------
# WeekCache: static data loaded once per week (~10 queries)
# -------------------------------------------------------------------

@dataclass
class WeekCache:
    """Data that does not change between subweeks within a single week."""

    # --- Team-level ---
    team_meta: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    roster_by_team: Dict[int, List[int]] = field(default_factory=dict)
    org_by_team: Dict[int, int] = field(default_factory=dict)
    team_strategy_by_team: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    bullpen_order_by_team: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)

    # --- Rotation (config + slots are static; state is mutable) ---
    rotation_by_team: Dict[int, Any] = field(default_factory=dict)
    rotation_slots_by_rotation: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)

    # --- Lineup / Defense (plans + roles are static; usage is mutable) ---
    position_plans_by_team: Dict[int, Dict[str, List[Dict]]] = field(default_factory=dict)
    lineup_roles_by_team: Dict[int, Dict[int, Dict]] = field(default_factory=dict)

    # --- Player-level (static attributes) ---
    player_rows: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    strategy_rows_by_player: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    xp_mods: Dict[int, Dict[str, float]] = field(default_factory=dict)
    pitch_hands: Dict[int, str] = field(default_factory=dict)
    position_weights: Any = None

    # --- Roster identity ---
    all_player_ids: Set[int] = field(default_factory=set)
    pitcher_ids_by_team: Dict[int, List[int]] = field(default_factory=dict)


# -------------------------------------------------------------------
# SubweekState: mutable data reloaded before each subweek (~4 queries)
# -------------------------------------------------------------------

@dataclass
class SubweekState:
    """Data that changes between subweeks due to post-game updates."""

    stamina: Dict[int, int] = field(default_factory=dict)
    injury_malus: Dict[int, Dict[str, float]] = field(default_factory=dict)
    engine_views: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    rotation_state_by_team: Dict[int, Any] = field(default_factory=dict)
    weekly_usage_by_team: Dict[int, Dict[str, Tuple]] = field(default_factory=dict)


# -------------------------------------------------------------------
# SubweekCache: combined view used by payload builders
# -------------------------------------------------------------------

@dataclass
class SubweekCache:
    """In-memory snapshot of everything needed to build game payloads."""

    # --- Team-level ---
    team_meta: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    roster_by_team: Dict[int, List[int]] = field(default_factory=dict)
    org_by_team: Dict[int, int] = field(default_factory=dict)
    team_strategy_by_team: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    bullpen_order_by_team: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)

    # --- Rotation ---
    rotation_by_team: Dict[int, Any] = field(default_factory=dict)
    rotation_slots_by_rotation: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    rotation_state_by_team: Dict[int, Any] = field(default_factory=dict)

    # --- Lineup / Defense ---
    position_plans_by_team: Dict[int, Dict[str, List[Dict]]] = field(default_factory=dict)
    weekly_usage_by_team: Dict[int, Dict[str, Tuple]] = field(default_factory=dict)
    lineup_roles_by_team: Dict[int, Dict[int, Dict]] = field(default_factory=dict)

    # --- Player-level ---
    player_rows: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    injury_malus: Dict[int, Dict[str, float]] = field(default_factory=dict)
    engine_views: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    stamina: Dict[int, int] = field(default_factory=dict)
    strategy_rows_by_player: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    xp_mods: Dict[int, Dict[str, float]] = field(default_factory=dict)
    pitch_hands: Dict[int, str] = field(default_factory=dict)
    position_weights: Any = None
    all_player_ids: Set[int] = field(default_factory=set)
    pitcher_ids_by_team: Dict[int, List[int]] = field(default_factory=dict)

    @classmethod
    def from_week_and_state(cls, wc: WeekCache, st: SubweekState) -> "SubweekCache":
        """Assemble a full SubweekCache from static WeekCache + mutable SubweekState."""
        return cls(
            # Static from WeekCache
            team_meta=wc.team_meta,
            roster_by_team=wc.roster_by_team,
            org_by_team=wc.org_by_team,
            team_strategy_by_team=wc.team_strategy_by_team,
            bullpen_order_by_team=wc.bullpen_order_by_team,
            rotation_by_team=wc.rotation_by_team,
            rotation_slots_by_rotation=wc.rotation_slots_by_rotation,
            position_plans_by_team=wc.position_plans_by_team,
            lineup_roles_by_team=wc.lineup_roles_by_team,
            player_rows=wc.player_rows,
            strategy_rows_by_player=wc.strategy_rows_by_player,
            xp_mods=wc.xp_mods,
            pitch_hands=wc.pitch_hands,
            position_weights=wc.position_weights,
            all_player_ids=wc.all_player_ids,
            pitcher_ids_by_team=wc.pitcher_ids_by_team,
            # Mutable from SubweekState
            stamina=st.stamina,
            injury_malus=st.injury_malus,
            engine_views=st.engine_views,
            rotation_state_by_team=st.rotation_state_by_team,
            weekly_usage_by_team=st.weekly_usage_by_team,
        )


# ===================================================================
# load_week_cache: static data, called once per week (~10 queries)
# ===================================================================

def load_week_cache(
    conn,
    team_ids: List[int],
    league_year_id: int,
    season_week: int,
    league_level_id: int,
) -> WeekCache:
    """
    Load all static (within-a-week) data for the given teams.
    ~10 bulk queries.  Safe to share across subweeks and threads (read-only).
    """
    from services.game_payload import (
        _get_core_tables,
        _get_roster_tables,
        DEFAULT_PLAYER_STRATEGY,
    )
    from services.defense_xp import compute_defensive_xp_mod_for_players

    wc = WeekCache()
    unique_team_ids = list(set(int(t) for t in team_ids))

    if not unique_team_ids:
        return wc

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
        wc.team_meta[tid] = dict(row)
        wc.org_by_team[tid] = int(row["orgID"])

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

        wc.roster_by_team.setdefault(tid, []).append(pid)
        wc.all_player_ids.add(pid)

        if ptype == "pitcher":
            wc.pitcher_ids_by_team.setdefault(tid, []).append(pid)

    all_pids = list(wc.all_player_ids)
    if not all_pids:
        return wc

    logger.info(
        "week_cache: %d teams, %d players — loading static bulk data",
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
        wc.player_rows[pid] = dict(row)

        raw_hand = row.get("pitch_hand")
        if raw_hand:
            s = str(raw_hand).strip().upper()
            if s and s[0] in ("L", "R"):
                wc.pitch_hands[pid] = s[0]

    # ---------------------------------------------------------------
    # 4) Position weights (static config)
    # ---------------------------------------------------------------
    from services.game_payload import _load_position_weights
    wc.position_weights = _load_position_weights(conn)

    # ---------------------------------------------------------------
    # 5) Defensive XP mods (bulk — 2 queries)
    # ---------------------------------------------------------------
    wc.xp_mods = compute_defensive_xp_mod_for_players(
        conn, all_pids, league_level_id
    )

    # ---------------------------------------------------------------
    # 6) Player strategies (bulk — single query)
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
        wc.strategy_rows_by_player.setdefault(pid, []).append(dict(row))

    # ---------------------------------------------------------------
    # 7) Team strategies (bulk — single query)
    # ---------------------------------------------------------------
    _load_team_strategies_bulk(conn, c_tables, unique_team_ids, wc)

    # ---------------------------------------------------------------
    # 8) Bullpen orders (bulk — single query)
    # ---------------------------------------------------------------
    _load_bullpen_orders_bulk(conn, c_tables, unique_team_ids, wc)

    # ---------------------------------------------------------------
    # 9) Rotation config + slots (2-3 queries, NOT state)
    # ---------------------------------------------------------------
    _load_rotation_config_bulk(conn, unique_team_ids, wc)

    # ---------------------------------------------------------------
    # 10) Position plans (bulk — single query)
    # ---------------------------------------------------------------
    _load_position_plans_bulk(conn, c_tables, unique_team_ids, wc)

    # ---------------------------------------------------------------
    # 11) Lineup roles (bulk — single query)
    # ---------------------------------------------------------------
    _load_lineup_roles_bulk(conn, c_tables, unique_team_ids, wc)

    logger.info("week_cache: fully loaded (%d teams, %d players)", len(unique_team_ids), len(all_pids))
    return wc


def _repair_malus_json(conn, player_ids: list) -> None:
    """
    Ensure all active injury events have the complete set of malus attributes
    defined by their injury type's impact_template_json.

    stamina_pct is a backend roster-management attribute — the engine never
    returns it as an injury effect.  This function adds any template attributes
    missing from malus_json (preserving engine-supplied values like contact).

    Safe to call on every subweek load — it is a no-op when nothing is missing.
    """
    if not player_ids:
        return

    from sqlalchemy import text as sa_text

    ph = ", ".join(f":p{i}" for i in range(len(player_ids)))
    params = {f"p{i}": pid for i, pid in enumerate(player_ids)}

    try:
        rows = conn.execute(sa_text(f"""
            SELECT pie.id AS event_id, pie.malus_json,
                   it.impact_template_json
            FROM player_injury_events pie
            JOIN player_injury_state pis ON pis.player_id = pie.player_id
            JOIN injury_types it ON it.id = pie.injury_type_id
            WHERE pie.player_id IN ({ph})
              AND pie.weeks_remaining > 0
              AND pis.status = 'injured'
        """), params).mappings().all()
    except Exception:
        logger.warning("_repair_malus_json: query failed", exc_info=True)
        return

    if not rows:
        return

    updates = []
    for row in rows:
        raw_template = row["impact_template_json"]
        if not raw_template:
            continue
        try:
            template = raw_template if isinstance(raw_template, dict) else json.loads(raw_template)
        except (TypeError, json.JSONDecodeError):
            continue

        try:
            existing = json.loads(row["malus_json"] or "{}")
            if not isinstance(existing, dict):
                existing = {}
        except (TypeError, json.JSONDecodeError):
            existing = {}

        updated = dict(existing)
        changed = False
        for attr, cfg in template.items():
            if attr in updated:
                continue  # engine-supplied value — keep it
            if isinstance(cfg, dict):
                try:
                    min_pct = float(cfg.get("min_pct", 0))
                    max_pct = float(cfg.get("max_pct", 0))
                    rolled_pct = round(random.uniform(min_pct, max_pct), 2)
                    updated[attr] = max(0.0, 1.0 - rolled_pct)
                    changed = True
                except (TypeError, ValueError):
                    continue

        if changed:
            updates.append({"event_id": int(row["event_id"]), "malus_json": json.dumps(updated)})

    if not updates:
        return

    try:
        conn.execute(sa_text(
            "UPDATE player_injury_events SET malus_json = :malus_json WHERE id = :event_id"
        ), updates)
        logger.info(
            "_repair_malus_json: added missing template attributes to %d injury events",
            len(updates),
        )
    except Exception:
        logger.warning("_repair_malus_json: UPDATE failed", exc_info=True)


# ===================================================================
# load_subweek_state: mutable data, called once per subweek (~4 queries)
# ===================================================================

def load_subweek_state(
    conn,
    week_cache: WeekCache,
    league_year_id: int,
    season_week: int,
) -> SubweekState:
    """
    Load only the mutable state that changes between subweeks.
    ~4 queries.  Called before each subweek's payload build.
    """
    from services.game_payload import (
        _get_core_tables,
        _build_engine_player_view_from_mapping,
    )
    from services.injuries import get_active_injury_malus_bulk
    from services.stamina import get_effective_stamina_bulk
    from services.rotation import _get_rotation_tables

    st = SubweekState()
    all_pids = list(week_cache.all_player_ids)
    unique_team_ids = list(week_cache.team_meta.keys())

    if not all_pids:
        return st

    # ---------------------------------------------------------------
    # 0) Repair any injury events stored with empty malus_json before
    #    this subweek's cache is built.  Injuries persisted before the
    #    template-fallback fix exist in the DB with malus_json = '{}',
    #    meaning they contribute zero malus and players play normally
    #    despite being marked as injured.  This one-time repair computes
    #    the correct malus from the injury type template and updates the row.
    # ---------------------------------------------------------------
    _repair_malus_json(conn, all_pids)

    # ---------------------------------------------------------------
    # 1) Injury maluses (bulk)
    # ---------------------------------------------------------------
    st.injury_malus = get_active_injury_malus_bulk(conn, all_pids)
    injured_count = sum(1 for v in st.injury_malus.values() if v)
    logger.info(
        "load_subweek_state: %d players total, %d have active injury malus",
        len(all_pids), injured_count,
    )
    if injured_count:
        for pid, malus in st.injury_malus.items():
            if malus:
                logger.info("  injury_malus player %d: %s", pid, malus)

    # ---------------------------------------------------------------
    # 2) Engine views (derived from static player_rows + mutable injury_malus)
    # ---------------------------------------------------------------
    for pid in all_pids:
        raw_mapping = week_cache.player_rows.get(pid)
        if raw_mapping is None:
            continue

        adjusted = dict(raw_mapping)
        malus = st.injury_malus.get(pid) or {}
        for attr, factor in malus.items():
            if attr == "stamina_pct":
                continue  # applied to stamina separately, not a _base column
            base_key = f"{attr}_base"
            if base_key not in adjusted:
                continue
            try:
                base_num = float(adjusted[base_key] or 0.0)
            except (TypeError, ValueError):
                base_num = 0.0
            try:
                factor_num = float(factor)
            except (TypeError, ValueError):
                factor_num = 1.0
            adjusted[base_key] = max(0.0, base_num * factor_num)

        st.engine_views[pid] = _build_engine_player_view_from_mapping(
            adjusted, week_cache.position_weights
        )

    # ---------------------------------------------------------------
    # 3) Stamina (bulk — single query)
    # ---------------------------------------------------------------
    st.stamina = get_effective_stamina_bulk(conn, all_pids, league_year_id)

    # ---------------------------------------------------------------
    # 4) Rotation state (single query)
    # ---------------------------------------------------------------
    r_tables = _get_rotation_tables()
    state_table = r_tables["state"]
    if unique_team_ids:
        state_rows = conn.execute(
            select(state_table).where(state_table.c.team_id.in_(unique_team_ids))
        ).mappings().all()

        for row in state_rows:
            tid = int(row["team_id"])
            st.rotation_state_by_team[tid] = dict(row)

    # ---------------------------------------------------------------
    # 5) Weekly usage (single query)
    # ---------------------------------------------------------------
    c_tables = _get_core_tables()
    _load_weekly_usage_bulk(conn, c_tables, unique_team_ids, league_year_id, season_week, st)

    logger.info(
        "subweek_state: refreshed mutable data (%d injuries, %d stamina rows, %d rotation states)",
        len(st.injury_malus), len(st.stamina), len(st.rotation_state_by_team),
    )
    return st


# ===================================================================
# Legacy: load_subweek_cache (full load, kept for backward compat)
# ===================================================================

def load_subweek_cache(
    conn,
    team_ids: List[int],
    league_year_id: int,
    season_week: int,
    league_level_id: int,
) -> SubweekCache:
    """
    Full load — equivalent to load_week_cache + load_subweek_state combined.
    Kept for backward compatibility with single-game payload endpoint.
    """
    wc = load_week_cache(conn, team_ids, league_year_id, season_week, league_level_id)
    st = load_subweek_state(conn, wc, league_year_id, season_week)
    return SubweekCache.from_week_and_state(wc, st)


# -------------------------------------------------------------------
# Internal bulk loaders (static — write to WeekCache)
# -------------------------------------------------------------------

def _load_team_strategies_bulk(conn, tables, team_ids, wc: WeekCache):
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
                wc.team_strategy_by_team[tid] = {
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
        iwl = strat.get("intentional_walk_list")
        if isinstance(iwl, str):
            try:
                strat["intentional_walk_list"] = json.loads(iwl)
            except (TypeError, json.JSONDecodeError):
                strat["intentional_walk_list"] = []
        elif iwl is None:
            strat["intentional_walk_list"] = []
        wc.team_strategy_by_team[tid] = strat

    for tid in team_ids:
        if tid not in found:
            wc.team_strategy_by_team[tid] = {
                **_DEFAULT_TEAM_STRATEGY, "team_id": tid
            }


def _load_bullpen_orders_bulk(conn, tables, team_ids, wc: WeekCache):
    """Bulk load team_bullpen_order for all teams."""
    tbo = tables.get("team_bullpen_order")
    if tbo is None:
        from sqlalchemy import Table, MetaData
        meta = MetaData()
        meta.reflect(bind=conn, only=["team_bullpen_order"])
        tbo = meta.tables.get("team_bullpen_order")
        if tbo is None:
            for tid in team_ids:
                wc.bullpen_order_by_team[tid] = []
            return

    rows = conn.execute(
        select(tbo).where(tbo.c.team_id.in_(team_ids)).order_by(
            tbo.c.team_id.asc(), tbo.c.slot.asc()
        )
    ).mappings().all()

    for tid in team_ids:
        wc.bullpen_order_by_team[tid] = []

    for row in rows:
        tid = int(row["team_id"])
        wc.bullpen_order_by_team.setdefault(tid, []).append({
            "slot": int(row["slot"]),
            "player_id": int(row["player_id"]),
            "role": row.get("role"),
        })


def _load_rotation_config_bulk(conn, team_ids, wc: WeekCache):
    """Bulk load rotation config and slots (NOT state) for all teams."""
    from services.rotation import _get_rotation_tables

    r_tables = _get_rotation_tables()
    rotation = r_tables["rotation"]
    slots = r_tables["slots"]

    # Rotation config
    rot_rows = conn.execute(
        select(rotation).where(rotation.c.team_id.in_(team_ids))
    ).mappings().all()

    rotation_ids = []
    for row in rot_rows:
        tid = int(row["team_id"])
        wc.rotation_by_team[tid] = dict(row)
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
            wc.rotation_slots_by_rotation.setdefault(rid, []).append(dict(row))


def _load_position_plans_bulk(conn, tables, team_ids, wc: WeekCache):
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
        wc.position_plans_by_team[tid] = {}

    for row in rows:
        tid = int(row["team_id"])
        pos = row["position_code"]
        wc.position_plans_by_team.setdefault(tid, {}).setdefault(pos, []).append(dict(row))


def _load_lineup_roles_bulk(conn, tables, team_ids, wc: WeekCache):
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
        wc.lineup_roles_by_team[tid] = {}

    for row in rows:
        tid = int(row["team_id"])
        slot = int(row["slot"])
        wc.lineup_roles_by_team.setdefault(tid, {})[slot] = dict(row)


# -------------------------------------------------------------------
# Internal bulk loaders (mutable — write to SubweekState)
# -------------------------------------------------------------------

def _load_weekly_usage_bulk(conn, tables, team_ids, league_year_id, season_week, st: SubweekState):
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
        st.weekly_usage_by_team[tid] = {}

    for row in rows:
        tid = int(row["team_id"])
        pos = row["position_code"]
        pid = int(row["player_id"])
        starts = int(row.get("starts_this_week") or row.get("starts", 0))

        team_usage = st.weekly_usage_by_team.setdefault(tid, {})
        if pos not in team_usage:
            team_usage[pos] = ({}, 0)

        usage_map, total = team_usage[pos]
        usage_map[pid] = usage_map.get(pid, 0) + starts
        team_usage[pos] = (usage_map, total + starts)


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
