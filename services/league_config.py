# services/league_config.py
"""
Key/value configuration tables with code defaults.

``league_config`` holds amateur-pipeline sizes and retirement thresholds;
``fa_config`` holds free-agency pricing constants. Both are optional: when a
table does not exist yet (migration not applied) the defaults below are used,
so nothing breaks on a database that has not been migrated.
"""

import logging
from decimal import Decimal
from typing import Any, Dict

from sqlalchemy import text

log = logging.getLogger(__name__)

LEAGUE_CONFIG_DEFAULTS: Dict[str, str] = {
    "hs_pool_target": "8864",
    "hs_entry_age": "15",
    "intam_pool_target": "6722",
    "intam_entry_age": "15",
    "intam_age_out": "23",
    "college_roster_floor": "25",
    "college_roster_target": "28",
    "undrafted_keep_ovr": "65",
    "never_signed_retire_age": "25",
    "walkon_age": "19",
    "retire_age_hard": "0",            # 0 = nobody retires on age alone
    "camp_regular_steps": "1",
    "camp_intense_steps": "2",
    "camp_intense_backfire": "0.25",
    "camp_max_steps": "4",
    "camp_max_backfire": "0.50",
    "retire_age_unsigned": "36",
    "retire_age_marginal": "33",
    "retire_marginal_ovr": "40",
}

FA_CONFIG_DEFAULTS: Dict[str, str] = {
    "dollar_per_war_default": "8000000",
    "dollar_per_war_min": "4000000",
    "dollar_per_war_max": "15000000",
    "market_min_history": "5",
    "market_lookback_years": "3",
    "market_extension_weight": "0.9",
    "war_blend_w0": "0.5",
    "war_blend_w1": "0.3",
    "war_blend_w2": "0.2",
    "war_regress_pa": "200",
    "war_regress_ip": "50",
    "fa_fallback_mlb_level": "8",
    "fa_fallback_minor_level": "4",
}


def _load(conn, table: str, defaults: Dict[str, str]) -> Dict[str, str]:
    cfg = dict(defaults)
    try:
        rows = conn.execute(text(f"SELECT config_key, config_value FROM {table}")).all()
    except Exception as e:  # table missing: run on defaults
        log.debug("%s not readable (%s); using defaults", table, e)
        return cfg
    for k, v in rows:
        if v is not None:
            cfg[str(k)] = str(v)
    return cfg


def get_league_config(conn) -> Dict[str, str]:
    return _load(conn, "league_config", LEAGUE_CONFIG_DEFAULTS)


def get_fa_config(conn) -> Dict[str, str]:
    return _load(conn, "fa_config", FA_CONFIG_DEFAULTS)


def cfg_int(cfg: Dict[str, Any], key: str, fallback: int) -> int:
    try:
        return int(float(cfg.get(key, fallback)))
    except (TypeError, ValueError):
        return fallback


def cfg_float(cfg: Dict[str, Any], key: str, fallback: float) -> float:
    try:
        return float(cfg.get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def cfg_dec(cfg: Dict[str, Any], key: str, fallback) -> Decimal:
    try:
        return Decimal(str(cfg.get(key, fallback)))
    except Exception:
        return Decimal(str(fallback))
