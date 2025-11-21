# services/defense_xp.py

from __future__ import annotations

from typing import Dict, Any, Iterable

from sqlalchemy import MetaData, Table, select, and_

from db import get_engine


POSITION_CODES = ["c", "fb", "sb", "tb", "ss", "lf", "cf", "rf", "dh", "p"]

_metadata = None
_xp_tables = None

# Cache config rows per league_level so we don't hit the DB repeatedly
_DEF_XP_CONFIG_CACHE: Dict[int, Dict[str, Dict[str, Any]]] = {}


def _get_xp_tables():
    """
    Reflect and cache:
      - player_position_experience
      - defense_xp_config
    """
    global _metadata, _xp_tables
    if _xp_tables is not None:
        return _xp_tables

    engine = get_engine()
    md = MetaData()

    player_position_experience = Table("player_position_experience", md, autoload_with=engine)
    defense_xp_config = Table("defense_xp_config", md, autoload_with=engine)

    _metadata = md
    _xp_tables = {
        "ppe": player_position_experience,
        "cfg": defense_xp_config,
    }
    return _xp_tables


def _default_config_for_position(pos: str) -> Dict[str, Any]:
    """
    Fallback config if defense_xp_config has no row for a given
    (league_level, position_code).
    """
    if pos == "p":
        return {
            "games_zero_malus": 30,
            "games_full_bonus": 60,
            "min_factor": -0.20,  # -20%
            "max_bonus": 0.05,    # +5%
        }
    else:
        return {
            "games_zero_malus": 160,
            "games_full_bonus": 320,
            "min_factor": -0.20,
            "max_bonus": 0.05,
        }


def _compute_xp_factor(
    starts: int,
    games_zero_malus: int,
    games_full_bonus: int,
    min_factor: float,
    max_bonus: float,
) -> float:
    """
    Compute multiplicative XP factor based on:
      - starts
      - thresholds (games_zero_malus, games_full_bonus)
      - min_factor (e.g. -0.20)
      - max_bonus (e.g. +0.05)

    Piecewise linear between:
      starts = 0              -> 1 + min_factor
      starts = games_zero     -> 1.0
      starts = games_full     -> 1 + max_bonus
    """
    if games_zero_malus <= 0 or games_full_bonus <= games_zero_malus:
        # Degenerate config; clamp to [1+min_factor, 1+max_bonus] based on starts
        if starts <= 0:
            return 1.0 + min_factor
        return 1.0 + max_bonus

    if starts <= 0:
        return 1.0 + min_factor

    if starts >= games_full_bonus:
        return 1.0 + max_bonus

    if starts <= games_zero_malus:
        t = starts / float(games_zero_malus)
        # t=0 => 1 + min_factor, t=1 => 1.0
        return (1.0 + min_factor) * (1.0 - t) + (1.0 * t)

    # Between zero-malus and full-bonus
    t = (starts - games_zero_malus) / float(games_full_bonus - games_zero_malus)
    return (1.0 * (1.0 - t)) + ((1.0 + max_bonus) * t)


def _load_config_for_league(conn, league_level_id: int) -> Dict[str, Dict[str, Any]]:
    """
    Load defense_xp_config rows for a league_level into a dict:
      {position_code: {games_zero_malus, games_full_bonus, min_factor, max_bonus}, ...}
    """
    if league_level_id in _DEF_XP_CONFIG_CACHE:
        return _DEF_XP_CONFIG_CACHE[league_level_id]

    tables = _get_xp_tables()
    cfg = tables["cfg"]

    cfg_by_pos: Dict[str, Dict[str, Any]] = {}

    stmt_cfg = select(
        cfg.c.position_code,
        cfg.c.games_zero_malus,
        cfg.c.games_full_bonus,
        cfg.c.min_factor,
        cfg.c.max_bonus,
    ).where(cfg.c.league_level == league_level_id)

    for row in conn.execute(stmt_cfg):
        pos = row.position_code
        cfg_by_pos[pos] = {
            "games_zero_malus": int(row.games_zero_malus),
            "games_full_bonus": int(row.games_full_bonus),
            "min_factor": float(row.min_factor),
            "max_bonus": float(row.max_bonus),
        }

    _DEF_XP_CONFIG_CACHE[league_level_id] = cfg_by_pos
    return cfg_by_pos


# -------------------------------------------------------------------
# Existing per-player function (kept for compatibility)
# -------------------------------------------------------------------

def compute_defensive_xp_mod_for_player(
    conn,
    player_id: int,
    league_level_id: int,
) -> Dict[str, float]:
    """
    Compute XP modifiers for ALL positions for a given player and league level.

    Returns a dict like:

      {"c": -0.18, "fb": 0.0, "sb": 0.02, ...}

    where each value is (xp_factor - 1.0).
    """
    tables = _get_xp_tables()
    ppe = tables["ppe"]

    # Load starts per position for this player
    starts_by_pos: Dict[str, int] = {pos: 0 for pos in POSITION_CODES}

    stmt_ppe = (
        select(ppe.c.position_code, ppe.c.starts)
        .where(ppe.c.player_id == player_id)
    )
    for row in conn.execute(stmt_ppe):
        pos = row.position_code
        if pos in starts_by_pos:
            starts_by_pos[pos] = int(row.starts or 0)

    cfg_by_pos = _load_config_for_league(conn, league_level_id)

    xp_mod: Dict[str, float] = {}

    for pos in POSITION_CODES:
        starts = starts_by_pos.get(pos, 0)
        cfg_pos = cfg_by_pos.get(pos) or _default_config_for_position(pos)

        factor = _compute_xp_factor(
            starts=starts,
            games_zero_malus=cfg_pos["games_zero_malus"],
            games_full_bonus=cfg_pos["games_full_bonus"],
            min_factor=cfg_pos["min_factor"],
            max_bonus=cfg_pos["max_bonus"],
        )
        xp_mod[pos] = factor - 1.0

    return xp_mod


# -------------------------------------------------------------------
# New bulk helper: all players at once
# -------------------------------------------------------------------

def compute_defensive_xp_mod_for_players(
    conn,
    player_ids: Iterable[int],
    league_level_id: int,
) -> Dict[int, Dict[str, float]]:
    """
    Bulk version of compute_defensive_xp_mod_for_player.

    Returns:
      {
        player_id: {
          "c": xp_mod_c,
          "fb": xp_mod_fb,
          ...
        },
        ...
      }
    """
    player_ids = [int(pid) for pid in player_ids]
    if not player_ids:
        return {}

    tables = _get_xp_tables()
    ppe = tables["ppe"]

    # Initialize starts_by_pos for each player
    starts_by_player: Dict[int, Dict[str, int]] = {
        pid: {pos: 0 for pos in POSITION_CODES}
        for pid in player_ids
    }

    # Load all starts for these players in one query
    stmt_ppe = (
        select(ppe.c.player_id, ppe.c.position_code, ppe.c.starts)
        .where(ppe.c.player_id.in_(player_ids))
    )

    for row in conn.execute(stmt_ppe):
        pid = int(row.player_id)
        pos = row.position_code
        if pid in starts_by_player and pos in starts_by_player[pid]:
            starts_by_player[pid][pos] = int(row.starts or 0)

    cfg_by_pos = _load_config_for_league(conn, league_level_id)

    result: Dict[int, Dict[str, float]] = {}

    for pid in player_ids:
        pos_starts = starts_by_player.get(pid, {})
        xp_mod: Dict[str, float] = {}

        for pos in POSITION_CODES:
            starts = pos_starts.get(pos, 0)
            cfg_pos = cfg_by_pos.get(pos) or _default_config_for_position(pos)

            factor = _compute_xp_factor(
                starts=starts,
                games_zero_malus=cfg_pos["games_zero_malus"],
                games_full_bonus=cfg_pos["games_full_bonus"],
                min_factor=cfg_pos["min_factor"],
                max_bonus=cfg_pos["max_bonus"],
            )
            xp_mod[pos] = factor - 1.0

        result[pid] = xp_mod

    return result
