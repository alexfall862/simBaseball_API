# services/pregame_injuries.py

from __future__ import annotations

import json
import random
from typing import Dict, Any, List, Tuple
import logging
from sqlalchemy import MetaData, Table, select, and_, or_

from db import get_engine


_metadata = None
_tables = None
_LEVEL_SIM_CFG_CACHE: Dict[int, Dict[str, Any]] = {}
log = logging.getLogger("services.pregame_injuries")

def _get_tables():
    """
    Reflect and cache:
      - injury_types
      - level_sim_config
    """
    global _metadata, _tables
    if _tables is not None:
        return _tables

    engine = get_engine()
    md = MetaData()

    injury_types = Table("injury_types", md, autoload_with=engine)
    level_sim_config = Table("level_sim_config", md, autoload_with=engine)

    _metadata = md
    _tables = {
        "injury_types": injury_types,
        "level_sim_config": level_sim_config,
    }
    return _tables


def _get_pregame_base_rate(conn, league_level_id: int) -> float:
    """
    Read pregame injury base rate from level_sim_config.baseline_outcomes_json.

    Cached per league_level_id for the life of the process.
    Handles TEXT/JSON columns that may come back as str, bytes, or dict.
    """
    tables = _get_tables()
    lsc = tables["level_sim_config"]

    # Use cached config if present
    if league_level_id in _LEVEL_SIM_CFG_CACHE:
        cfg = _LEVEL_SIM_CFG_CACHE[league_level_id]
    else:
        row = conn.execute(
            select(lsc.c.baseline_outcomes_json)
            .where(lsc.c.league_level == league_level_id)
        ).first()

        if not row or row[0] is None:
            _LEVEL_SIM_CFG_CACHE[league_level_id] = {}
            log.info(
                "no level_sim_config baseline_outcomes_json for league_level",
                extra={"league_level_id": league_level_id},
            )
            return 0.0

        raw = row[0]

        try:
            # If DB driver already returned a dict (JSON type), use it directly
            if isinstance(raw, (dict, list)):
                cfg = raw
            else:
                # Normalize to text then json.loads
                if isinstance(raw, (bytes, bytearray)):
                    text = raw.decode("utf-8")
                else:
                    text = str(raw)
                cfg = json.loads(text)
        except (TypeError, json.JSONDecodeError) as e:
            log.warning(
                "failed to parse baseline_outcomes_json",
                extra={
                    "league_level_id": league_level_id,
                    "raw_type": type(raw).__name__,
                    "raw_repr": repr(raw),
                    "error": str(e),
                },
            )
            cfg = {}

        _LEVEL_SIM_CFG_CACHE[league_level_id] = cfg

    rate = cfg.get("pregame_injury_base_rate")
    if rate is None:
        log.info(
            "no pregame_injury_base_rate set; using 0.0",
            extra={"league_level_id": league_level_id},
        )
        return 0.0

    try:
        val = float(rate)
    except (TypeError, ValueError) as e:
        log.warning(
            "invalid pregame_injury_base_rate; using 0.0",
            extra={
                "league_level_id": league_level_id,
                "rate": rate,
                "error": str(e),
            },
        )
        return 0.0

    log.info(
        "pregame injury base rate loaded",
        extra={"league_level_id": league_level_id, "base_rate": val},
    )
    return val


# Injury risk → multiplier
_RISK_MULTIPLIERS: Dict[str, float] = {
    "iron man": 0.5,
    "normal": 1.0,
    "needs rest": 1.5,
    "fragile": 2.0,
    "high": 1.5,
}


def _get_risk_multiplier(injury_risk: str | None) -> float:
    if not injury_risk:
        return 1.0
    key = str(injury_risk).strip().lower()
    return _RISK_MULTIPLIERS.get(key, 1.0)


def _load_pregame_injury_types_for_group(conn, target_group: str) -> List[Dict[str, Any]]:
    """
    target_group:
      - 'pitcher'  -> target IN ('pitcher','both')
      - 'position' -> target IN ('position','both')
    """
    tables = _get_tables()
    it = tables["injury_types"]

    conditions = [it.c.timeframe == "pregame"]

    if target_group == "pitcher":
        conditions.append(it.c.target.in_(["pitcher", "both"]))
    elif target_group == "position":
        conditions.append(it.c.target.in_(["position", "both"]))
    else:
        # Fallback: only 'both'
        conditions.append(it.c.target == "both")

    stmt = select(it).where(and_(*conditions))
    rows = conn.execute(stmt).mappings().all()

    return [dict(r) for r in rows]


def _choose_weighted_type(
    rng: random.Random,
    injury_type_rows: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    """
    Choose one injury type by weighting with frequency_weight.
    """
    if not injury_type_rows:
        return None

    weights: List[float] = []
    for row in injury_type_rows:
        try:
            w = float(row.get("frequency_weight") or 0.0)
        except (TypeError, ValueError):
            w = 0.0
        weights.append(max(w, 0.0))

    total_weight = sum(weights)
    if total_weight <= 0:
        return None

    pick = rng.uniform(0.0, total_weight)
    accum = 0.0
    for row, w in zip(injury_type_rows, weights):
        accum += w
        if pick <= accum:
            return row

    # Fallback: last
    return injury_type_rows[-1]


def _generate_effects_for_injury_type(
    rng: random.Random,
    injury_type_row: Dict[str, Any],
) -> Dict[str, float]:
    """
    effects_json is expected like:

      {
        "contact": {"min_pct": 0.5, "max_pct": 0.8},
        "stamina_pct": {"min_pct": 1.0, "max_pct": 1.0}
      }

    We sample a multiplier for each key between [min_pct, max_pct].
    """
    raw = injury_type_row.get("effects_json")
    if not raw:
        return {}

    try:
        data = raw if isinstance(raw, dict) else json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}

    effects: Dict[str, float] = {}

    for attr_name, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        try:
            min_pct = float(cfg.get("min_pct"))
            max_pct = float(cfg.get("max_pct"))
        except (TypeError, ValueError):
            continue

        if max_pct < min_pct:
            min_pct, max_pct = max_pct, min_pct

        val = rng.uniform(min_pct, max_pct)
        effects[attr_name] = val

    return effects


def _sample_duration_weeks(
    rng: random.Random,
    injury_type_row: Dict[str, Any],
) -> int:
    """
    Sample injury length in weeks from min/mean/max.

    Uses triangular distribution with mode at mean.
    """
    try:
        min_w = float(injury_type_row.get("min_length_weeks") or injury_type_row.get("min_length") or 1.0)
        mean_w = float(injury_type_row.get("mean_length_weeks") or injury_type_row.get("mean_length") or min_w)
        max_w = float(injury_type_row.get("max_length_weeks") or injury_type_row.get("max_length") or mean_w)
    except (TypeError, ValueError):
        return 1

    if max_w < min_w:
        min_w, max_w = max_w, min_w
    if mean_w < min_w:
        mean_w = min_w
    if mean_w > max_w:
        mean_w = max_w

    val = rng.triangular(min_w, max_w, mean_w)
    weeks = int(round(val))
    return max(1, weeks)


def _apply_effects_to_player(
    player: Dict[str, Any],
    effects: Dict[str, float],
):
    """
    Apply injury multipliers directly to the player dict for this game:

      - 'stamina_pct' scales player['stamina']
      - any other key 'foo' scales player['foo_base'] if present
    """
    if not effects:
        return

    # Stamina
    if "stamina_pct" in effects:
        factor = effects["stamina_pct"]
        try:
            base_stam = float(player.get("stamina") or 0.0)
        except (TypeError, ValueError):
            base_stam = 0.0
        new_stam = int(max(0.0, base_stam * factor))
        player["stamina"] = new_stam

    # Other attributes (e.g. 'contact', 'power', etc. -> scale *_base fields)
    for attr, factor in effects.items():
        if attr == "stamina_pct":
            continue

        base_key = f"{attr}_base"
        if base_key not in player:
            continue

        try:
            base_val = float(player.get(base_key) or 0.0)
        except (TypeError, ValueError):
            base_val = 0.0

        player[base_key] = base_val * factor


def roll_pregame_injuries_for_team(
    conn,
    league_level_id: int,
    team_id: int,
    players_by_id: Dict[int, Dict[str, Any]],
    rng: random.Random,
) -> List[Dict[str, Any]]:
    """
    Roll pregame injuries for this team.

    - Overall per-player probability comes from:
        base_rate (level_sim_config) * risk_multiplier(injury_risk)
    - If an injury triggers, we pick:
        injury_types with timeframe='pregame' and target matching
        pitcher/position/both, then select weighted by frequency_weight.
    - We generate:
        - a duration in weeks
        - multiplicative attribute effects
      and apply those effects directly to players_by_id for THIS GAME ONLY.

    Returns a list of injury descriptors for the payload, e.g.:

      [
        {
          "player_id": 123,
          "injury_type_id": 1,
          "code": "strained_pec",
          "name": "strained pec",
          "timeframe": "pregame",
          "duration_weeks": 4,
          "effects": {"contact": 0.73, "stamina_pct": 0.0},
        },
        ...
      ]

    These are *not* persisted; the idea is that the engine will later report
    back injuries (pregame + ingame) and the canonical post-game processor
    will commit them to player_injury_events/player_injury_state.
    """
    if not players_by_id:
        return []

    base_rate = _get_pregame_base_rate(conn, league_level_id)
    if base_rate <= 0.0:
        # No pregame injuries configured
        return []

    # Preload injury types for pitchers vs position players
    pitcher_types = _load_pregame_injury_types_for_group(conn, "pitcher")
    position_types = _load_pregame_injury_types_for_group(conn, "position")

    if not pitcher_types and not position_types:
        return []

    injuries: List[Dict[str, Any]] = []

    for pid, p in players_by_id.items():
        # Determine base per-player probability
        risk_mult = _get_risk_multiplier(p.get("injury_risk"))
        prob = base_rate * risk_mult

        ptype = (p.get("ptype") or "").strip().lower()

        roll = rng.random()

        log.info(
            "pregame_injury_roll",
            extra={
                "team_id": team_id,
                "player_id": pid,
                "ptype": ptype,
                "injury_risk": p.get("injury_risk"),
                "base_rate": base_rate,
                "risk_mult": risk_mult,
                "prob": prob,
                "roll": roll,
            },
        )

        if prob <= 0.0:
            continue

        if roll >= prob:
            continue

        if ptype == "pitcher":
            type_pool = pitcher_types or position_types  # fallback to 'both' group
        else:
            type_pool = position_types or pitcher_types

        if not type_pool:
            continue

        it_row = _choose_weighted_type(rng, type_pool)
        if not it_row:
            continue

        effects = _generate_effects_for_injury_type(rng, it_row)
        duration_weeks = _sample_duration_weeks(rng, it_row)

        log.info(
            "pregame_injury_applied",
            extra={
                "team_id": team_id,
                "player_id": pid,
                "ptype": ptype,
                "injury_type_id": int(it_row["id"]),
                "injury_code": it_row.get("code") or it_row.get("name"),
                "duration_weeks": duration_weeks,
                "effects": effects,
            },
        )

        # Apply in-place effects to this player's payload view
        _apply_effects_to_player(p, effects)

        injuries.append(
            {
                "player_id": pid,
                "injury_type_id": int(it_row["id"]),
                "code": it_row.get("code") or it_row.get("name"),
                "name": it_row.get("name"),
                "timeframe": "pregame",
                "duration_weeks": duration_weeks,
                "effects": effects,
            }
        )

    return injuries
