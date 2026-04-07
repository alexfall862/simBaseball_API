# services/allstar.py
"""
All-Star Game: manual roster entry, one-off exhibition game.
Stats do NOT accumulate into season totals; stamina/injuries DO persist.
All pitchers get shortest leash (pulltend=quick) and 20-pitch maximum.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text

log = logging.getLogger("app")

# All-Star pitcher overrides
ALLSTAR_PITCHPULL = 20
ALLSTAR_PULLTEND = "quick"

LINEUP_POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]


# =====================================================================
# Event Creation (manual rosters)
# =====================================================================

def create_allstar_event(
    conn,
    league_year_id: int,
    league_level: int,
    home: Dict[str, Any],
    away: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new All-Star event with manually specified rosters.

    Each side dict must contain:
      - label: str (e.g. "AL", "NL")
      - starting_pitchers: list of 12 player_ids
      - relief_pitchers: list of 4 player_ids
      - lineup: list of 9 dicts with {player_id, position}
      - bench: list of 11 player_ids
    """
    _validate_side(home, "home")
    _validate_side(away, "away")

    metadata = {"league_level": league_level}

    conn.execute(sa_text("""
        INSERT INTO special_events
            (league_year_id, event_type, status, created_at, metadata_json)
        VALUES
            (:lyid, 'allstar', 'setup', NOW(), :meta)
    """), {"lyid": league_year_id, "meta": json.dumps(metadata)})

    event_id = conn.execute(sa_text("SELECT LAST_INSERT_ID()")).scalar()

    # Insert rosters for both sides
    _insert_manual_roster(conn, event_id, home)
    _insert_manual_roster(conn, event_id, away)

    conn.execute(sa_text("""
        UPDATE special_events SET status = 'roster_ready' WHERE id = :eid
    """), {"eid": event_id})

    log.info("allstar: created event %d (level %d) with manual rosters", event_id, league_level)

    return {
        "event_id": event_id,
        "league_year_id": league_year_id,
        "league_level": league_level,
    }


def _validate_side(side: Dict[str, Any], name: str):
    """Validate a side's roster structure."""
    label = side.get("label")
    if not label:
        raise ValueError(f"{name}: label is required")

    sp = side.get("starting_pitchers", [])
    rp = side.get("relief_pitchers", [])
    lineup = side.get("lineup", [])
    bench = side.get("bench", [])

    if len(sp) != 12:
        raise ValueError(f"{name}: need exactly 12 starting pitchers, got {len(sp)}")
    if len(rp) != 4:
        raise ValueError(f"{name}: need exactly 4 relief pitchers, got {len(rp)}")
    if len(lineup) != 9:
        raise ValueError(f"{name}: need exactly 9 lineup entries, got {len(lineup)}")
    if len(bench) != 11:
        raise ValueError(f"{name}: need exactly 11 bench players, got {len(bench)}")

    # Validate lineup positions
    positions = [entry["position"].upper() for entry in lineup]
    for pos in positions:
        if pos not in LINEUP_POSITIONS:
            raise ValueError(f"{name}: invalid lineup position '{pos}'")

    # Check for duplicate player IDs
    all_ids = list(sp) + list(rp) + [e["player_id"] for e in lineup] + list(bench)
    if len(set(all_ids)) != len(all_ids):
        raise ValueError(f"{name}: duplicate player IDs detected")


def _insert_manual_roster(conn, event_id: int, side: Dict[str, Any]):
    """Insert all players from a manually specified side."""
    label = side["label"]

    # Starting pitchers — first one is the game starter
    for i, pid in enumerate(side["starting_pitchers"]):
        conn.execute(sa_text("""
            INSERT INTO special_event_rosters
                (event_id, team_label, player_id, position_code, is_starter, source)
            VALUES (:eid, :label, :pid, 'SP', :starter, 'manual')
        """), {
            "eid": event_id, "label": label,
            "pid": int(pid), "starter": 1 if i == 0 else 0,
        })

    # Relief pitchers
    for pid in side["relief_pitchers"]:
        conn.execute(sa_text("""
            INSERT INTO special_event_rosters
                (event_id, team_label, player_id, position_code, is_starter, source)
            VALUES (:eid, :label, :pid, 'RP', 0, 'manual')
        """), {"eid": event_id, "label": label, "pid": int(pid)})

    # Lineup (starters at their defensive/DH positions)
    for entry in side["lineup"]:
        conn.execute(sa_text("""
            INSERT INTO special_event_rosters
                (event_id, team_label, player_id, position_code, is_starter, source)
            VALUES (:eid, :label, :pid, :pos, 1, 'manual')
        """), {
            "eid": event_id, "label": label,
            "pid": int(entry["player_id"]),
            "pos": entry["position"].upper(),
        })

    # Bench
    for pid in side["bench"]:
        conn.execute(sa_text("""
            INSERT INTO special_event_rosters
                (event_id, team_label, player_id, position_code, is_starter, source)
            VALUES (:eid, :label, :pid, 'BENCH', 0, 'manual')
        """), {"eid": event_id, "label": label, "pid": int(pid)})


# =====================================================================
# Ad-hoc Simulation
# =====================================================================

def simulate_allstar_game(conn, event_id: int) -> Dict[str, Any]:
    """
    Build payloads for both All-Star sides and send to the engine.
    Results are stored in special_events.metadata_json (not in gamelist).
    """
    from services.game_payload import (
        get_game_constants,
        get_level_configs_normalized_bulk,
        build_engine_player_views_bulk,
        get_ballpark_info,
        get_all_injury_types,
        _get_level_rules_for_league,
    )
    from services.game_engine_client import simulate_games_batch

    # Load event
    event = conn.execute(sa_text("""
        SELECT id, league_year_id, status, metadata_json
        FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()

    if not event:
        raise ValueError(f"Event {event_id} not found")
    if event["status"] not in ("roster_ready", "setup"):
        raise ValueError(f"Event {event_id} status is '{event['status']}', expected 'roster_ready'")

    league_year_id = int(event["league_year_id"])
    meta = json.loads(event["metadata_json"]) if event["metadata_json"] else {}
    league_level = int(meta.get("league_level", 9))

    # Load rosters grouped by team_label
    roster_rows = conn.execute(sa_text("""
        SELECT ser.player_id, ser.team_label, ser.position_code, ser.is_starter
        FROM special_event_rosters ser
        WHERE ser.event_id = :eid
        ORDER BY ser.team_label, ser.is_starter DESC
    """), {"eid": event_id}).mappings().all()

    if not roster_rows:
        raise ValueError(f"No roster found for event {event_id}")

    sides: Dict[str, List[Dict]] = {}
    for r in roster_rows:
        label = r["team_label"]
        sides.setdefault(label, []).append({
            "player_id": int(r["player_id"]),
            "position": r["position_code"],
            "is_starter": bool(r["is_starter"]),
        })

    labels = sorted(sides.keys())
    if len(labels) < 2:
        raise ValueError(f"Need 2 teams, found {len(labels)}: {labels}")

    home_label = labels[0]
    away_label = labels[1]

    # Load shared engine config
    rules = _get_level_rules_for_league(conn, league_level)
    use_dh = bool(rules.get("dh", True))
    game_constants = get_game_constants(conn)
    level_configs_raw = get_level_configs_normalized_bulk(conn, [league_level])
    level_configs = {str(k): v for k, v in level_configs_raw.items()}
    rules_by_level = {str(league_level): rules}
    injury_types = get_all_injury_types(conn)

    # Pick a "home" ballpark
    home_players = sides[home_label]
    first_home_pid = home_players[0]["player_id"]
    home_team_id = conn.execute(sa_text("""
        SELECT c.team_id FROM contracts c
        WHERE c.player_id = :pid AND c.status = 'active'
        LIMIT 1
    """), {"pid": first_home_pid}).scalar()
    ballpark = get_ballpark_info(conn, home_team_id) if home_team_id else {}

    # Build both sides
    home_side = _build_allstar_side(
        conn, home_label, sides[home_label],
        league_level, league_year_id, use_dh,
    )
    away_side = _build_allstar_side(
        conn, away_label, sides[away_label],
        league_level, league_year_id, use_dh,
    )

    # Compose game payload
    game_payload = {
        "game_id": None,
        "league_level_id": league_level,
        "league_year_id": league_year_id,
        "season_week": 0,
        "season_subweek": "a",
        "ballpark": ballpark,
        "home_side": home_side,
        "away_side": away_side,
        "random_seed": None,
    }

    # Send to engine
    results = simulate_games_batch(
        [game_payload], "a",
        game_constants=game_constants,
        level_configs=level_configs,
        rules=rules_by_level,
        injury_types=injury_types,
        league_year_id=league_year_id,
        season_week=0,
        league_level=league_level,
    )

    if not results:
        raise ValueError("Engine returned no results for allstar game")

    result = results[0]

    # Extract scores
    game_result_data = result.get("result") or {}
    home_score = int(game_result_data.get("home_score", 0) or result.get("home_score", 0))
    away_score = int(game_result_data.get("away_score", 0) or result.get("away_score", 0))

    winner_label = home_label if home_score > away_score else away_label
    if home_score == away_score:
        winner_label = "tie"

    # Store result in metadata_json
    game_result = {
        "home_label": home_label,
        "away_label": away_label,
        "home_score": home_score,
        "away_score": away_score,
        "winner_label": winner_label,
        "boxscore": result.get("boxscore") or game_result_data.get("boxscore"),
    }
    meta["game_result"] = game_result

    conn.execute(sa_text("""
        UPDATE special_events
        SET status = 'completed', completed_at = NOW(),
            metadata_json = :meta
        WHERE id = :eid
    """), {"eid": event_id, "meta": json.dumps(meta)})

    log.info(
        "allstar: event %d simulated — %s %d, %s %d (winner: %s)",
        event_id, home_label, home_score, away_label, away_score, winner_label,
    )

    return {
        "event_id": event_id,
        "home_label": home_label,
        "away_label": away_label,
        "home_score": home_score,
        "away_score": away_score,
        "winner_label": winner_label,
    }


def _build_allstar_side(
    conn, label: str, roster: List[Dict],
    league_level: int, league_year_id: int, use_dh: bool,
) -> Dict[str, Any]:
    """
    Build an engine-facing team side from allstar roster players.
    Uses explicit lineup/defense from the roster entries.
    All pitchers get shortest leash + 20-pitch max.
    """
    from services.game_payload import (
        build_engine_player_views_bulk,
        _load_player_strategies_bulk,
        DEFAULT_PLAYER_STRATEGY,
        POSITION_CODES,
    )
    from services.stamina import get_effective_stamina_bulk
    from services.defense_xp import compute_defensive_xp_mod_for_players

    player_ids = [p["player_id"] for p in roster]

    # Look up each player's real org for strategy borrowing
    org_rows = conn.execute(sa_text("""
        SELECT c.player_id, tm.orgID
        FROM contracts c
        JOIN teams tm ON tm.id = c.team_id
        WHERE c.player_id IN ({})
          AND c.status = 'active'
    """.format(",".join(str(pid) for pid in player_ids)))).mappings().all()

    org_by_player = {int(r["player_id"]): int(r["orgID"]) for r in org_rows}
    orgs = list(org_by_player.values())
    primary_org = max(set(orgs), key=orgs.count) if orgs else 1

    # Load player engine views
    engine_views = build_engine_player_views_bulk(conn, player_ids)

    # Stamina
    stamina_by_player = get_effective_stamina_bulk(conn, player_ids, league_year_id)

    # Strategies
    strategies_by_player = _load_player_strategies_bulk(conn, player_ids, org_id=primary_org)

    # Defensive XP
    xp_by_player = compute_defensive_xp_mod_for_players(conn, player_ids, league_level)

    players_by_id: Dict[int, Dict] = {}
    for pid in player_ids:
        base_view = engine_views.get(pid)
        if base_view is None:
            continue

        ep = dict(base_view)

        # Stamina
        raw_stamina = int(stamina_by_player.get(pid, 100))
        injury_stam_pct = ep.pop("_injury_stamina_pct", None)
        if injury_stam_pct is not None:
            raw_stamina = int(max(0.0, raw_stamina * injury_stam_pct))
        ep["stamina"] = raw_stamina
        ep["benched_by_injury"] = (injury_stam_pct is not None and raw_stamina == 0)

        # Strategy
        strat = strategies_by_player.get(pid) or DEFAULT_PLAYER_STRATEGY.copy()

        # Override ALL pitchers with shortest leash + 20-pitch max
        is_pitcher = (ep.get("ptype") or "").lower() == "pitcher"
        if is_pitcher:
            strat["pitchpull"] = ALLSTAR_PITCHPULL
            strat["pulltend"] = ALLSTAR_PULLTEND

        ep.update(strat)

        # Defensive XP
        ep["defensive_xp_mod"] = xp_by_player.get(pid, {pos: 0.0 for pos in POSITION_CODES})

        players_by_id[pid] = ep

    # Determine starting pitcher, lineup, defense, bench from roster entries
    starter_id = None
    available_pitcher_ids = []
    lineup_ids = []
    bench_ids = []
    defense = {}

    for entry in roster:
        pid = entry["player_id"]
        if pid not in players_by_id:
            continue
        pos = entry["position"]

        if pos == "SP":
            if entry["is_starter"] and starter_id is None:
                starter_id = pid
            else:
                available_pitcher_ids.append(pid)
        elif pos == "RP":
            available_pitcher_ids.append(pid)
        elif pos == "BENCH":
            bench_ids.append(pid)
        else:
            # Lineup player with defensive position
            lineup_ids.append(pid)
            if pos != "DH":
                defense[pos] = pid

    # Fallback: if no starter marked, use first SP
    if starter_id is None:
        sp_ids = [e["player_id"] for e in roster if e["position"] == "SP" and e["player_id"] in players_by_id]
        if sp_ids:
            starter_id = sp_ids[0]
            available_pitcher_ids = [pid for pid in available_pitcher_ids if pid != starter_id]

    return {
        "team_id": 0,
        "team_abbrev": label,
        "team_name": f"All-Stars ({label})",
        "team_nickname": label,
        "org_id": primary_org,
        "players": list(players_by_id.values()),
        "starting_pitcher_id": starter_id,
        "available_pitcher_ids": available_pitcher_ids,
        "defense": defense,
        "lineup": lineup_ids,
        "bench": bench_ids,
        "pregame_injuries": [],
        "team_strategy": {},
        "bullpen_order": [],
        "vs_hand": None,
    }


# =====================================================================
# Roster Queries & Results
# =====================================================================

def get_event_rosters(conn, event_id: int) -> Dict[str, Any]:
    """Get rosters for an All-Star event."""
    rows = conn.execute(sa_text("""
        SELECT ser.*, p.firstName, p.lastName, p.ptype,
               t.team_abbrev
        FROM special_event_rosters ser
        JOIN simbbPlayers p ON p.id = ser.player_id
        LEFT JOIN (
            SELECT c.player_id, tm.team_abbrev
            FROM contracts c
            JOIN teams tm ON tm.id = c.team_id
            WHERE c.status = 'active'
        ) t ON t.player_id = ser.player_id
        WHERE ser.event_id = :eid
        ORDER BY ser.team_label, ser.is_starter DESC, ser.position_code
    """), {"eid": event_id}).mappings().all()

    rosters: Dict[str, List] = {}
    for r in rows:
        label = r["team_label"]
        rosters.setdefault(label, []).append({
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}".strip(),
            "team": r["team_abbrev"],
            "position": r["position_code"],
            "is_starter": bool(r["is_starter"]),
            "source": r["source"],
        })

    return {"event_id": event_id, "rosters": rosters}


def get_allstar_results(conn, event_id: int) -> Optional[Dict[str, Any]]:
    """Get results for a completed All-Star game (stored in metadata_json)."""
    event = conn.execute(sa_text("""
        SELECT id, league_year_id, status, metadata_json, completed_at
        FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()

    if not event:
        return None

    meta = json.loads(event["metadata_json"]) if event["metadata_json"] else {}
    rosters = get_event_rosters(conn, event_id)

    return {
        "event_id": event_id,
        "league_year_id": int(event["league_year_id"]),
        "league_level": meta.get("league_level"),
        "status": event["status"],
        "completed_at": str(event["completed_at"]) if event["completed_at"] else None,
        "game_result": meta.get("game_result"),
        "rosters": rosters["rosters"],
    }
