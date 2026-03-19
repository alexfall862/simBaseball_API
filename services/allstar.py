# services/allstar.py
"""
All-Star Game: ad-hoc exhibition game with WAR-based roster selection.
Stats do NOT accumulate into season totals; stamina/injuries DO persist.

Supports all league levels:
  - Levels with conferences (e.g. MLB level 9: AL/NL) → split by conference
  - Levels without conferences → random split into Team A / Team B
"""

import json
import logging
import random as stdlib_random
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text

from db import get_engine

log = logging.getLogger("app")

# Position slots per side roster (~26 players)
POSITION_SLOTS = {
    "C": 2, "1B": 1, "2B": 1, "3B": 1, "SS": 1,
    "LF": 1, "CF": 1, "RF": 1, "DH": 1,
    "SP": 5, "RP": 5,
}
ROSTER_SIZE = 26


# =====================================================================
# Event Creation
# =====================================================================

def create_allstar_event(
    conn, league_year_id: int, league_level: int = 9,
) -> Dict[str, Any]:
    """
    Create a new All-Star event and auto-generate rosters for the given level.
    Returns event_id and roster summary.
    """
    # Check for existing allstar event at this level
    existing = conn.execute(sa_text("""
        SELECT id FROM special_events
        WHERE league_year_id = :lyid AND event_type = 'allstar'
          AND JSON_EXTRACT(metadata_json, '$.league_level') = :level
    """), {"lyid": league_year_id, "level": league_level}).first()

    if existing:
        raise ValueError(
            f"All-Star event already exists for level {league_level} "
            f"(event_id={existing[0]}). Wipe it first to recreate."
        )

    metadata = {"league_level": league_level}

    conn.execute(sa_text("""
        INSERT INTO special_events
            (league_year_id, event_type, status, created_at, metadata_json)
        VALUES
            (:lyid, 'allstar', 'setup', NOW(), :meta)
    """), {"lyid": league_year_id, "meta": json.dumps(metadata)})

    event_id = conn.execute(sa_text("SELECT LAST_INSERT_ID()")).scalar()

    rosters = generate_allstar_rosters(conn, event_id, league_year_id, league_level)

    conn.execute(sa_text("""
        UPDATE special_events SET status = 'roster_ready' WHERE id = :eid
    """), {"eid": event_id})

    team_counts = {label: len(players) for label, players in rosters.items()}
    log.info("allstar: created event %d (level %d) with %s", event_id, league_level, team_counts)

    return {
        "event_id": event_id,
        "league_year_id": league_year_id,
        "league_level": league_level,
        "rosters": rosters,
    }


# =====================================================================
# Roster Generation
# =====================================================================

def generate_allstar_rosters(
    conn, event_id: int, league_year_id: int, league_level: int,
) -> Dict[str, List[Dict]]:
    """
    Auto-select All-Star rosters by WAR.
    For levels with conferences → one team per conference.
    For levels without conferences → random 50/50 split.
    """
    # Check if this level has conferences
    conferences = conn.execute(sa_text("""
        SELECT DISTINCT conference FROM teams
        WHERE team_level = :level AND conference IS NOT NULL AND conference != ''
    """), {"level": league_level}).all()
    conf_names = [r[0] for r in conferences]

    if len(conf_names) >= 2:
        # Conference-based split (e.g. AL/NL for MLB)
        team_labels = conf_names[:2]
        rosters = {}
        for conf in team_labels:
            players = _get_war_leaders(conn, league_year_id, league_level, conference=conf)
            selected = _fill_roster(players)
            _insert_roster(conn, event_id, conf, selected)
            rosters[conf] = selected
    else:
        # No conferences — get all players, random split
        players = _get_war_leaders(conn, league_year_id, league_level, conference=None)
        # Take top ROSTER_SIZE*2 and shuffle-split
        pool = players[:ROSTER_SIZE * 3]  # extra buffer
        stdlib_random.shuffle(pool)

        team_a = _fill_roster(pool[:len(pool) // 2])
        # Remove used IDs from pool for team B
        used_ids = {p["player_id"] for p in team_a}
        remaining = [p for p in pool if p["player_id"] not in used_ids]
        team_b = _fill_roster(remaining)

        _insert_roster(conn, event_id, "Team A", team_a)
        _insert_roster(conn, event_id, "Team B", team_b)
        rosters = {"Team A": team_a, "Team B": team_b}

    return rosters


def _fill_roster(players: List[Dict]) -> List[Dict]:
    """Pick ROSTER_SIZE players: fill position slots first, then best WAR remaining."""
    selected = []
    used_ids = set()

    by_pos: Dict[str, List[Dict]] = {}
    for p in players:
        by_pos.setdefault(p["position"], []).append(p)

    # Fill each position slot
    for pos, count in POSITION_SLOTS.items():
        candidates = by_pos.get(pos, [])
        filled = 0
        for c in candidates:
            if c["player_id"] in used_ids:
                continue
            is_starter = filled == 0
            selected.append({**c, "is_starter": is_starter})
            used_ids.add(c["player_id"])
            filled += 1
            if filled >= count:
                break

    # Fill remaining with best WAR
    remaining_needed = ROSTER_SIZE - len(selected)
    for p in players:
        if remaining_needed <= 0:
            break
        if p["player_id"] not in used_ids:
            selected.append({**p, "is_starter": False})
            used_ids.add(p["player_id"])
            remaining_needed -= 1

    return selected


def _insert_roster(conn, event_id: int, team_label: str, players: List[Dict]):
    """Insert roster players into special_event_rosters."""
    for p in players:
        conn.execute(sa_text("""
            INSERT INTO special_event_rosters
                (event_id, team_label, player_id, position_code,
                 is_starter, source)
            VALUES
                (:eid, :label, :pid, :pos, :starter, 'auto')
        """), {
            "eid": event_id, "label": team_label,
            "pid": p["player_id"], "pos": p["position"],
            "starter": 1 if p.get("is_starter") else 0,
        })


def _get_war_leaders(
    conn, league_year_id: int, league_level: int,
    conference: Optional[str] = None,
) -> List[Dict]:
    """
    Get players sorted by WAR for a given level (optionally filtered by conference).
    """
    conf_filter = "AND tm.conference = :conf" if conference else ""
    params = {"lyid": league_year_id, "level": league_level}
    if conference:
        params["conf"] = conference

    # Batting WAR
    bat_sql = sa_text(f"""
        SELECT bs.player_id, p.firstName, p.lastName, p.ptype,
               tm.team_abbrev, tm.id AS team_id,
               bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
               bs.home_runs, bs.walks, bs.runs,
               fs.position_code
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        LEFT JOIN player_fielding_stats fs ON fs.player_id = bs.player_id
            AND fs.league_year_id = bs.league_year_id
            AND fs.team_id = bs.team_id
        WHERE bs.league_year_id = :lyid
          AND tm.team_level = :level
          {conf_filter}
          AND bs.at_bats >= 30
        ORDER BY fs.innings DESC
    """)
    bat_rows = conn.execute(bat_sql, params).mappings().all()

    # League averages
    lg = conn.execute(sa_text(f"""
        SELECT
            SUM(bs.hits + bs.walks) AS lg_on_base,
            SUM(bs.at_bats + bs.walks) AS lg_pa,
            SUM(bs.hits + bs.doubles_hit + 2*bs.triples + 3*bs.home_runs) AS lg_tb,
            SUM(bs.at_bats) AS lg_ab,
            SUM(bs.runs) AS lg_runs
        FROM player_batting_stats bs
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid AND tm.team_level = :level
    """), {"lyid": league_year_id, "level": league_level}).mappings().first()

    lg_pa = float(lg["lg_pa"] or 1)
    lg_ab = float(lg["lg_ab"] or 1)
    lg_runs = float(lg["lg_runs"] or 1)
    lg_obp = float(lg["lg_on_base"] or 0) / lg_pa
    lg_slg = float(lg["lg_tb"] or 0) / lg_ab
    lg_ops = lg_obp + lg_slg
    pa_per_run = lg_pa / lg_runs if lg_runs > 0 else 25.0
    repl_ops = lg_ops * 0.80

    # Pitching league avg
    lg_pit = conn.execute(sa_text(f"""
        SELECT SUM(ps.earned_runs) AS lg_er,
               SUM(ps.innings_pitched_outs) AS lg_ipo
        FROM player_pitching_stats ps
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid AND tm.team_level = :level
    """), {"lyid": league_year_id, "level": league_level}).mappings().first()

    lg_ipo = float(lg_pit["lg_ipo"] or 1)
    lg_er = float(lg_pit["lg_er"] or 0)
    lg_era = lg_er * 27.0 / lg_ipo if lg_ipo > 0 else 4.50
    repl_era = lg_era / 0.80

    players: Dict[int, Dict] = {}

    # Position player WAR
    seen_bat = set()
    for row in bat_rows:
        pid = int(row["player_id"])
        if pid in seen_bat:
            continue
        seen_bat.add(pid)

        ab = float(row["at_bats"])
        h = float(row["hits"])
        d = float(row["doubles_hit"])
        t = float(row["triples"])
        hr = float(row["home_runs"])
        bb = float(row["walks"])
        pa = ab + bb
        if pa == 0:
            continue

        obp = (h + bb) / pa
        slg = (h + d + 2 * t + 3 * hr) / ab if ab > 0 else 0.0
        ops = obp + slg
        batting_runs = (ops - repl_ops) * pa / pa_per_run
        war = batting_runs / 10.0

        pos = str(row["position_code"] or "DH").upper()

        players[pid] = {
            "player_id": pid,
            "name": f"{row['firstName']} {row['lastName']}".strip(),
            "team_abbrev": row["team_abbrev"],
            "team_id": int(row["team_id"]),
            "position": pos,
            "war": round(war, 2),
        }

    # Pitcher WAR
    pit_sql = sa_text(f"""
        SELECT ps.player_id, p.firstName, p.lastName,
               tm.team_abbrev, tm.id AS team_id,
               ps.innings_pitched_outs, ps.earned_runs, ps.games_started
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid
          AND tm.team_level = :level
          {conf_filter}
          AND ps.innings_pitched_outs >= 30
    """)
    pit_rows = conn.execute(pit_sql, params).mappings().all()

    for row in pit_rows:
        pid = int(row["player_id"])
        ipo = float(row["innings_pitched_outs"])
        er = float(row["earned_runs"])
        ip = ipo / 3.0
        player_era = er * 9.0 / ip if ip > 0 else 99.0
        pit_runs = (repl_era - player_era) * ip / 9.0
        war = pit_runs / 10.0

        gs = int(row["games_started"] or 0)
        pos = "SP" if gs > 0 else "RP"

        if pid in players:
            players[pid]["war"] = round(players[pid]["war"] + war, 2)
        else:
            players[pid] = {
                "player_id": pid,
                "name": f"{row['firstName']} {row['lastName']}".strip(),
                "team_abbrev": row["team_abbrev"],
                "team_id": int(row["team_id"]),
                "position": pos,
                "war": round(war, 2),
            }

    return sorted(players.values(), key=lambda p: p["war"], reverse=True)


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
        _load_player_strategies_bulk,
        DEFAULT_PLAYER_STRATEGY,
    )
    from services.stamina import get_effective_stamina_bulk
    from services.lineups import build_defense_and_lineup
    from services.defense_xp import compute_defensive_xp_mod_for_players
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

    # Load rosters
    roster_rows = conn.execute(sa_text("""
        SELECT ser.player_id, ser.team_label, ser.position_code, ser.is_starter
        FROM special_event_rosters ser
        WHERE ser.event_id = :eid
        ORDER BY ser.team_label, ser.is_starter DESC
    """), {"eid": event_id}).mappings().all()

    if not roster_rows:
        raise ValueError(f"No roster found for event {event_id}")

    # Group by team_label
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

    home_label = labels[0]  # alphabetically first is home
    away_label = labels[1]

    # Load shared engine config
    rules = _get_level_rules_for_league(conn, league_level)
    use_dh = bool(rules.get("dh", True))
    game_constants = get_game_constants(conn)
    level_configs_raw = get_level_configs_normalized_bulk(conn, [league_level])
    level_configs = {str(k): v for k, v in level_configs_raw.items()}
    rules_by_level = {str(league_level): rules}
    injury_types = get_all_injury_types(conn)

    # Pick a "home" ballpark (use the first home-side player's team ballpark)
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

    # Compose game payload (no game_id since this isn't in gamelist)
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
    Borrows each player's attributes, strategies, and stamina from their real team.
    """
    from services.game_payload import (
        build_engine_player_views_bulk,
        _load_player_strategies_bulk,
        DEFAULT_PLAYER_STRATEGY,
        POSITION_CODES,
    )
    from services.stamina import get_effective_stamina_bulk
    from services.lineups import build_defense_and_lineup
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

    # Use the most common org as the "team" org for strategy loading
    org_by_player = {int(r["player_id"]): int(r["orgID"]) for r in org_rows}
    orgs = list(org_by_player.values())
    primary_org = max(set(orgs), key=orgs.count) if orgs else 1

    # Load player engine views (attributes, ratings, injuries)
    engine_views = build_engine_player_views_bulk(conn, player_ids)

    # Stamina
    stamina_by_player = get_effective_stamina_bulk(conn, player_ids, league_year_id)

    # Strategies — load from each player's own org
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
        strat = strategies_by_player.get(pid) or DEFAULT_PLAYER_STRATEGY
        ep.update(strat)

        # Defensive XP
        ep["defensive_xp_mod"] = xp_by_player.get(pid, {pos: 0.0 for pos in POSITION_CODES})

        players_by_id[pid] = ep

    # Pick starting pitcher: highest-WAR SP from the roster
    sp_candidates = [
        p for p in roster
        if p["position"] == "SP" and p["player_id"] in players_by_id
    ]
    if sp_candidates:
        starter_id = sp_candidates[0]["player_id"]  # roster already WAR-sorted
    else:
        # Fallback: any pitcher
        pitcher_ids = [
            pid for pid, data in players_by_id.items()
            if (data.get("ptype") or "").lower() == "pitcher"
        ]
        starter_id = pitcher_ids[0] if pitcher_ids else player_ids[0]

    # Available pitchers
    all_pitcher_ids = [
        pid for pid, data in players_by_id.items()
        if (data.get("ptype") or "").lower() == "pitcher" and pid != starter_id
    ]

    # Get opponent SP hand for lineup building (we don't know yet, default None)
    # Use a placeholder team_id for defense/lineup building
    first_team_id = roster[0].get("team_id") if roster else None
    if first_team_id is None:
        # Resolve from contract
        first_team_id = conn.execute(sa_text("""
            SELECT c.team_id FROM contracts c
            WHERE c.player_id = :pid AND c.status = 'active' LIMIT 1
        """), {"pid": roster[0]["player_id"]}).scalar() or 0

    # Build defense + lineup using the allstar player pool
    defense, lineup_ids, bench_ids = build_defense_and_lineup(
        conn=conn,
        team_id=first_team_id,
        league_level_id=league_level,
        league_year_id=league_year_id,
        season_week=0,
        vs_hand=None,
        players_by_id=players_by_id,
        starter_id=starter_id,
        use_dh=use_dh,
    )

    return {
        "team_id": 0,
        "team_abbrev": label,
        "team_name": f"All-Stars ({label})",
        "team_nickname": label,
        "org_id": primary_org,
        "players": list(players_by_id.values()),
        "starting_pitcher_id": starter_id,
        "available_pitcher_ids": all_pitcher_ids,
        "defense": defense,
        "lineup": lineup_ids,
        "bench": bench_ids,
        "pregame_injuries": [],
        "team_strategy": {},
        "bullpen_order": [],
        "vs_hand": None,
    }


# =====================================================================
# Roster Queries & Admin Overrides
# =====================================================================

def update_roster(
    conn, event_id: int, changes: List[Dict[str, Any]]
) -> Dict[str, int]:
    """
    Admin roster overrides: add/remove players.
    changes: [{"action": "add"/"remove", "player_id": int, "team_label": str, ...}]
    """
    added = 0
    removed = 0

    for change in changes:
        action = change.get("action")
        pid = int(change["player_id"])

        if action == "remove":
            conn.execute(sa_text("""
                DELETE FROM special_event_rosters
                WHERE event_id = :eid AND player_id = :pid
            """), {"eid": event_id, "pid": pid})
            removed += 1

        elif action == "add":
            conn.execute(sa_text("""
                INSERT INTO special_event_rosters
                    (event_id, team_label, player_id, position_code,
                     is_starter, source)
                VALUES
                    (:eid, :label, :pid, :pos, :starter, 'manual')
                AS new_row ON DUPLICATE KEY UPDATE
                    team_label = new_row.team_label,
                    position_code = new_row.position_code,
                    source = 'manual'
            """), {
                "eid": event_id,
                "label": change.get("team_label", ""),
                "pid": pid,
                "pos": change.get("position_code", ""),
                "starter": 1 if change.get("is_starter") else 0,
            })
            added += 1

    return {"added": added, "removed": removed}


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
