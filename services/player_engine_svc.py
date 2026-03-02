"""
Service wrapper for the player_engine package.
Handles engine access, transactions, and exposes high-level operations.
"""
import logging
from sqlalchemy import text

from db import get_engine
from player_engine import generate_player, generate_players, progress_player, progress_all_players

log = logging.getLogger(__name__)

SEED_TABLES = [
    "growth_curves",
    "regions",
    "cities",
    "forenames",
    "surnames",
    "pitch_types",
    "potential_weights",
]

def svc_generate_players(count: int, age: int = 15) -> list[dict]:
    """Generate *count* new players at the given starting age.
    Returns list of player dicts (each includes the new ``id``)."""
    engine = get_engine()
    with engine.begin() as conn:
        players = generate_players(conn, count, age=age)
    log.info("player_engine: generated %d players (age=%d)", len(players), age)
    return players


def svc_progress_single(player_id: int) -> dict:
    """Progress one player by 1 year. Returns summary dict."""
    engine = get_engine()
    with engine.begin() as conn:
        progress_player(conn, player_id)
    log.info("player_engine: progressed player %d", player_id)
    return {"player_id": player_id, "status": "ok"}


def svc_progress_all(max_age: int = 45) -> dict:
    """Batch-progress every player under *max_age*. Returns count."""
    engine = get_engine()
    with engine.begin() as conn:
        count = progress_all_players(conn, max_age=max_age)
    log.info("player_engine: batch progressed %d players (max_age=%d)", count, max_age)
    return {"progressed": count}


def svc_seed_table_status() -> list[dict]:
    """Return row counts for all player-engine seed tables."""
    engine = get_engine()
    results = []
    with engine.connect() as conn:
        for table in SEED_TABLES:
            try:
                count = conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar()
                results.append({"table": table, "rows": count})
            except Exception:
                results.append({"table": table, "rows": -1})
    return results
