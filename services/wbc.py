# services/wbc.py
"""
World Baseball Classic: 16-team tournament with pool play and knockout rounds.
Uses virtual teams (team_level=99) mapped to player nationalities.
Stats do NOT accumulate into season totals; stamina/injuries DO persist.
"""

import logging
from itertools import combinations
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text

from db import get_engine

log = logging.getLogger("app")

WBC_TEAM_LEVEL = 99  # Virtual team level for WBC country teams
ROSTER_SIZE = 26


# =====================================================================
# Country Identification
# =====================================================================

def identify_eligible_countries(conn) -> List[Dict[str, Any]]:
    """
    Identify countries with enough players (>=26) for a WBC team.
    USA players: intorusa='usa', area=state → country='USA'
    International: intorusa='international', area=country_name

    Returns sorted list of {country, player_count}.
    """
    sql = sa_text("""
        SELECT
            CASE WHEN intorusa = 'usa' THEN 'USA' ELSE area END AS country,
            COUNT(*) AS player_count
        FROM simbbPlayers
        WHERE intorusa IS NOT NULL AND intorusa != ''
        GROUP BY country
        HAVING player_count >= :min_players
        ORDER BY player_count DESC
    """)

    rows = conn.execute(sql, {"min_players": ROSTER_SIZE}).mappings().all()
    return [{"country": r["country"], "player_count": int(r["player_count"])} for r in rows]


# =====================================================================
# Event Creation
# =====================================================================

def create_wbc_event(
    conn,
    league_year_id: int,
    countries: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a WBC event:
    1. Select top 16 eligible countries (or use admin override)
    2. Create special_events row
    3. Create virtual team rows (team_level=99)
    4. Create wbc_teams rows
    5. Assign pool groups (4 groups of 4)
    """
    # Get eligible countries
    eligible = identify_eligible_countries(conn)
    eligible_names = [e["country"] for e in eligible]

    if countries:
        # Validate admin-selected countries
        for c in countries:
            if c not in eligible_names:
                raise ValueError(f"Country '{c}' has fewer than {ROSTER_SIZE} eligible players")
        selected = countries[:16]
    else:
        selected = eligible_names[:16]

    if len(selected) < 4:
        raise ValueError(f"Need at least 4 countries, only found {len(selected)}")

    # Create special event
    conn.execute(sa_text("""
        INSERT INTO special_events
            (league_year_id, event_type, status, created_at)
        VALUES
            (:lyid, 'wbc', 'setup', NOW())
    """), {"lyid": league_year_id})
    event_id = conn.execute(sa_text("SELECT LAST_INSERT_ID()")).scalar()

    # Get a reference org and ballpark for virtual teams
    ref = conn.execute(sa_text("""
        SELECT orgID, ballpark_name FROM teams WHERE team_level = 9 LIMIT 1
    """)).mappings().first()
    ref_org = int(ref["orgID"]) if ref else 1
    ref_ballpark = ref["ballpark_name"] if ref else "default"

    # Ensure the WBC level exists in the levels table (FK constraint)
    existing_level = conn.execute(sa_text(
        "SELECT id FROM levels WHERE id = :lvl"
    ), {"lvl": WBC_TEAM_LEVEL}).scalar()
    if not existing_level:
        conn.execute(sa_text(
            "INSERT INTO levels (id, league_level) VALUES (:lvl, 'wbc')"
        ), {"lvl": WBC_TEAM_LEVEL})

    # Get next available team ID (teams.id is not auto_increment)
    max_id = conn.execute(sa_text("SELECT COALESCE(MAX(id), 0) FROM teams")).scalar()
    next_team_id = int(max_id) + 1

    # Create virtual teams and WBC entries
    pool_groups = "ABCD"
    created_teams = []

    for i, country in enumerate(selected):
        country_code = _country_code(country)
        pool = pool_groups[i % len(pool_groups)] if i < 16 else None

        team_id = next_team_id + i

        # Create virtual team row
        conn.execute(sa_text("""
            INSERT INTO teams
                (id, team_abbrev, team_name, team_nickname, orgID,
                 team_level, ballpark_name)
            VALUES
                (:id, :abbrev, :name, :nickname, :org,
                 :level, :ballpark)
        """), {
            "id": team_id,
            "abbrev": country_code[:6],
            "name": country,
            "nickname": "WBC",
            "org": ref_org,
            "level": WBC_TEAM_LEVEL,
            "ballpark": ref_ballpark,
        })

        # Create wbc_teams row
        conn.execute(sa_text("""
            INSERT INTO wbc_teams
                (event_id, country_name, country_code, pool_group, seed)
            VALUES
                (:eid, :name, :code, :pool, :seed)
        """), {
            "eid": event_id,
            "name": country,
            "code": country_code,
            "pool": pool,
            "seed": i + 1,
        })

        created_teams.append({
            "team_id": team_id,
            "country": country,
            "code": country_code,
            "pool": pool,
        })

    # Store team_id mapping in event metadata
    import json
    team_map = {t["code"]: t["team_id"] for t in created_teams}
    conn.execute(sa_text("""
        UPDATE special_events
        SET metadata_json = :meta, status = 'teams_created'
        WHERE id = :eid
    """), {
        "eid": event_id,
        "meta": json.dumps({"team_map": team_map}),
    })

    log.info("wbc: created event %d with %d countries", event_id, len(created_teams))

    return {
        "event_id": event_id,
        "teams": created_teams,
    }


def generate_wbc_rosters(conn, event_id: int) -> Dict[str, Any]:
    """
    Auto-select rosters for each WBC country team.
    Picks top ~26 players by WAR (or raw batting/pitching stats if no WAR data).
    """
    import json

    event = conn.execute(sa_text("""
        SELECT * FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()

    if not event:
        raise ValueError(f"Event {event_id} not found")

    meta = json.loads(event["metadata_json"] or "{}")
    team_map = meta.get("team_map", {})

    wbc_teams = conn.execute(sa_text("""
        SELECT country_name, country_code FROM wbc_teams WHERE event_id = :eid
    """), {"eid": event_id}).mappings().all()

    roster_summary = {}

    for wt in wbc_teams:
        country = wt["country_name"]
        code = wt["country_code"]

        # Get players for this country
        if country == "USA":
            player_sql = sa_text("""
                SELECT p.id AS player_id, p.firstName, p.lastName, p.ptype
                FROM simbbPlayers p
                WHERE p.intorusa = 'usa'
                ORDER BY RAND()
                LIMIT 200
            """)
            players = conn.execute(player_sql).mappings().all()
        else:
            player_sql = sa_text("""
                SELECT p.id AS player_id, p.firstName, p.lastName, p.ptype
                FROM simbbPlayers p
                WHERE p.intorusa = 'international' AND p.area = :country
                ORDER BY RAND()
                LIMIT 200
            """)
            players = conn.execute(player_sql, {"country": country}).mappings().all()

        # Try to get WAR-based selection using batting/pitching stats
        league_year_id = int(event["league_year_id"])
        player_ids = [int(p["player_id"]) for p in players]

        if not player_ids:
            roster_summary[code] = {"count": 0, "country": country}
            continue

        # Get batting stats for these players
        bat_stats = {}
        if player_ids:
            placeholders = ",".join(str(pid) for pid in player_ids)
            bat_rows = conn.execute(sa_text(f"""
                SELECT player_id,
                       at_bats, hits, home_runs, walks, runs
                FROM player_batting_stats
                WHERE league_year_id = :lyid
                  AND player_id IN ({placeholders})
            """), {"lyid": league_year_id}).mappings().all()
            for br in bat_rows:
                ab = float(br["at_bats"] or 0)
                h = float(br["hits"] or 0)
                bb = float(br["walks"] or 0)
                pa = ab + bb
                ops = ((h + bb) / pa + h / ab) if pa > 0 and ab > 0 else 0.0
                bat_stats[int(br["player_id"])] = ops

        # Get pitching stats
        pit_stats = {}
        if player_ids:
            pit_rows = conn.execute(sa_text(f"""
                SELECT player_id,
                       innings_pitched_outs, earned_runs
                FROM player_pitching_stats
                WHERE league_year_id = :lyid
                  AND player_id IN ({placeholders})
            """), {"lyid": league_year_id}).mappings().all()
            for pr in pit_rows:
                ipo = float(pr["innings_pitched_outs"] or 0)
                er = float(pr["earned_runs"] or 0)
                era = er * 27.0 / ipo if ipo > 0 else 99.0
                pit_stats[int(pr["player_id"])] = 10.0 - era  # Higher is better

        # Score players and select top ROSTER_SIZE
        scored = []
        for p in players:
            pid = int(p["player_id"])
            ptype = str(p["ptype"] or "").lower()
            score = 0.0
            if ptype == "pitcher":
                score = pit_stats.get(pid, 0.0)
            else:
                score = bat_stats.get(pid, 0.0)
            scored.append((pid, p, score))

        scored.sort(key=lambda x: x[2], reverse=True)
        selected = scored[:ROSTER_SIZE]

        for pid, p, _ in selected:
            ptype = str(p["ptype"] or "").lower()
            pos = "SP" if ptype == "pitcher" else "DH"
            conn.execute(sa_text("""
                INSERT INTO special_event_rosters
                    (event_id, team_label, player_id, position_code,
                     is_starter, source)
                VALUES
                    (:eid, :label, :pid, :pos, 0, 'auto')
                AS new_row
                ON DUPLICATE KEY UPDATE team_label = new_row.team_label
            """), {
                "eid": event_id, "label": code,
                "pid": pid, "pos": pos,
            })

        roster_summary[code] = {"count": len(selected), "country": country}

    conn.execute(sa_text("""
        UPDATE special_events SET status = 'roster_ready' WHERE id = :eid
    """), {"eid": event_id})

    return roster_summary


# =====================================================================
# Pool Play
# =====================================================================

def generate_pool_games(conn, event_id: int) -> Dict[str, Any]:
    """
    Generate round-robin pool play games (6 games per 4-team pool, 24 total).
    """
    import json

    event = conn.execute(sa_text("""
        SELECT * FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()
    if not event:
        raise ValueError(f"Event {event_id} not found")

    meta = json.loads(event["metadata_json"] or "{}")
    team_map = meta.get("team_map", {})

    wbc_teams = conn.execute(sa_text("""
        SELECT country_code, pool_group FROM wbc_teams
        WHERE event_id = :eid AND pool_group IS NOT NULL
        ORDER BY pool_group, seed
    """), {"eid": event_id}).mappings().all()

    # Group by pool
    pools: Dict[str, List[str]] = {}
    for wt in wbc_teams:
        pools.setdefault(wt["pool_group"], []).append(wt["country_code"])

    engine = get_engine()
    league_year_id = int(event["league_year_id"])
    league_year = conn.execute(sa_text(
        "SELECT league_year FROM league_years WHERE id = :lyid"
    ), {"lyid": league_year_id}).scalar()

    from services.schedule_generator import add_series

    total_games = 0
    pool_week = 100  # Use high week numbers for WBC

    for pool_letter, codes in sorted(pools.items()):
        # Round-robin: each pair plays once
        for i, (c1, c2) in enumerate(combinations(codes, 2)):
            t1 = team_map.get(c1)
            t2 = team_map.get(c2)
            if not t1 or not t2:
                continue

            add_series(
                engine,
                league_year=league_year,
                league_level=WBC_TEAM_LEVEL,
                home_team_id=t1,
                away_team_id=t2,
                week=pool_week,
                games=1,
                game_type="wbc",
            )
            total_games += 1

        pool_week += 1

    conn.execute(sa_text("""
        UPDATE special_events SET status = 'pool_play' WHERE id = :eid
    """), {"eid": event_id})

    log.info("wbc: generated %d pool games for event %d", total_games, event_id)
    return {"games_created": total_games, "pools": {k: v for k, v in pools.items()}}


def process_pool_results(conn, event_id: int) -> Dict[str, Any]:
    """
    Update wbc_teams win/loss from completed pool play game_results.
    Returns pool standings.
    """
    import json

    event = conn.execute(sa_text("""
        SELECT * FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()
    meta = json.loads(event["metadata_json"] or "{}")
    team_map = meta.get("team_map", {})

    # Reverse map: team_id → country_code
    id_to_code = {v: k for k, v in team_map.items()}

    # Get all WBC game results
    results = conn.execute(sa_text("""
        SELECT winning_team_id, losing_team_id
        FROM game_results
        WHERE game_type = 'wbc'
          AND league_level = :level
    """), {"level": WBC_TEAM_LEVEL}).mappings().all()

    # Count wins/losses per team
    wins: Dict[int, int] = {}
    losses: Dict[int, int] = {}
    for r in results:
        wtid = int(r["winning_team_id"])
        ltid = int(r["losing_team_id"])
        wins[wtid] = wins.get(wtid, 0) + 1
        losses[ltid] = losses.get(ltid, 0) + 1

    # Update wbc_teams
    for code, tid in team_map.items():
        w = wins.get(tid, 0)
        l = losses.get(tid, 0)
        conn.execute(sa_text("""
            UPDATE wbc_teams
            SET pool_wins = :w, pool_losses = :l
            WHERE event_id = :eid AND country_code = :code
        """), {"w": w, "l": l, "eid": event_id, "code": code})

    # Get standings by pool
    standings = conn.execute(sa_text("""
        SELECT country_name, country_code, pool_group, pool_wins, pool_losses
        FROM wbc_teams
        WHERE event_id = :eid
        ORDER BY pool_group, pool_wins DESC, pool_losses ASC
    """), {"eid": event_id}).mappings().all()

    pool_standings: Dict[str, List] = {}
    for s in standings:
        pool_standings.setdefault(s["pool_group"], []).append({
            "country": s["country_name"],
            "code": s["country_code"],
            "wins": int(s["pool_wins"]),
            "losses": int(s["pool_losses"]),
        })

    return {"standings": pool_standings}


# =====================================================================
# Knockout Bracket
# =====================================================================

def generate_knockout_bracket(conn, event_id: int) -> Dict[str, Any]:
    """
    Create knockout bracket from pool results.
    Top 2 per pool advance. QF: A1vB2, B1vA2, C1vD2, D1vC2.
    SF and Final are single games.
    """
    import json

    event = conn.execute(sa_text("""
        SELECT * FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()
    meta = json.loads(event["metadata_json"] or "{}")
    team_map = meta.get("team_map", {})

    # Get pool standings (top 2 per pool)
    standings = conn.execute(sa_text("""
        SELECT country_code, pool_group, pool_wins, pool_losses
        FROM wbc_teams
        WHERE event_id = :eid AND pool_group IS NOT NULL
        ORDER BY pool_group, pool_wins DESC, pool_losses ASC
    """), {"eid": event_id}).mappings().all()

    pools: Dict[str, List] = {}
    for s in standings:
        pools.setdefault(s["pool_group"], []).append(s)

    # QF matchups: A1vB2, B1vA2, C1vD2, D1vC2
    qf_matchups = [
        ("A", 0, "B", 1),  # A1 vs B2
        ("B", 0, "A", 1),  # B1 vs A2
        ("C", 0, "D", 1),  # C1 vs D2
        ("D", 0, "C", 1),  # D1 vs C2
    ]

    engine = get_engine()
    league_year_id = int(event["league_year_id"])
    league_year = conn.execute(sa_text(
        "SELECT league_year FROM league_years WHERE id = :lyid"
    ), {"lyid": league_year_id}).scalar()

    from services.schedule_generator import add_series

    ko_week = 110  # Knockout round week
    created = []

    for snum, (pool_a, idx_a, pool_b, idx_b) in enumerate(qf_matchups, start=1):
        if pool_a not in pools or pool_b not in pools:
            continue
        if idx_a >= len(pools[pool_a]) or idx_b >= len(pools[pool_b]):
            continue

        team_a_code = pools[pool_a][idx_a]["country_code"]
        team_b_code = pools[pool_b][idx_b]["country_code"]
        team_a_id = team_map.get(team_a_code)
        team_b_id = team_map.get(team_b_code)

        if not team_a_id or not team_b_id:
            continue

        conn.execute(sa_text("""
            INSERT INTO playoff_series
                (league_year_id, league_level, round, series_number,
                 team_a_id, team_b_id, seed_a, seed_b,
                 series_length, status, start_week, conference)
            VALUES
                (:lyid, :level, 'QF', :snum,
                 :team_a, :team_b, 1, 2,
                 1, 'pending', :week, 'WBC')
        """), {
            "lyid": league_year_id, "level": WBC_TEAM_LEVEL,
            "snum": snum,
            "team_a": team_a_id, "team_b": team_b_id,
            "week": ko_week,
        })

        add_series(
            engine, league_year=league_year, league_level=WBC_TEAM_LEVEL,
            home_team_id=team_a_id, away_team_id=team_b_id,
            week=ko_week, games=1, game_type="wbc",
        )

        created.append({
            "round": "QF", "matchup": f"{team_a_code} vs {team_b_code}",
        })

    conn.execute(sa_text("""
        UPDATE special_events SET status = 'knockout' WHERE id = :eid
    """), {"eid": event_id})

    return {"series_created": created}


def advance_wbc_knockout(conn, event_id: int) -> Dict[str, Any]:
    """
    Advance WBC knockout rounds: QF→SF→F.
    Uses playoff_series with conference='WBC'.
    """
    import json

    event = conn.execute(sa_text("""
        SELECT * FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()
    meta = json.loads(event["metadata_json"] or "{}")
    team_map = meta.get("team_map", {})

    league_year_id = int(event["league_year_id"])
    league_year = conn.execute(sa_text(
        "SELECT league_year FROM league_years WHERE id = :lyid"
    ), {"lyid": league_year_id}).scalar()

    engine = get_engine()
    from services.schedule_generator import add_series

    # Check current round status
    rounds = conn.execute(sa_text("""
        SELECT round,
               COUNT(*) AS total,
               SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS done
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
          AND conference = 'WBC'
        GROUP BY round
    """), {"lyid": league_year_id, "level": WBC_TEAM_LEVEL}).mappings().all()

    round_status = {r["round"]: {"total": int(r["total"]), "done": int(r["done"])} for r in rounds}

    # Find latest complete round
    ko_order = ["QF", "SF", "F"]
    current_round = None
    for rnd in ko_order:
        info = round_status.get(rnd)
        if info and info["total"] == info["done"]:
            current_round = rnd

    if not current_round:
        return {"error": "No complete knockout round found"}

    next_idx = ko_order.index(current_round) + 1
    if next_idx >= len(ko_order):
        # Tournament complete!
        winner = conn.execute(sa_text("""
            SELECT winner_team_id FROM playoff_series
            WHERE league_year_id = :lyid AND league_level = :level
              AND conference = 'WBC' AND round = 'F'
            LIMIT 1
        """), {"lyid": league_year_id, "level": WBC_TEAM_LEVEL}).scalar()

        conn.execute(sa_text("""
            UPDATE special_events SET status = 'complete', completed_at = NOW()
            WHERE id = :eid
        """), {"eid": event_id})

        return {"status": "complete", "winner_team_id": winner}

    next_round = ko_order[next_idx]

    # Get winners from current round
    winners = conn.execute(sa_text("""
        SELECT winner_team_id, series_number
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
          AND conference = 'WBC' AND round = :rnd
        ORDER BY series_number
    """), {"lyid": league_year_id, "level": WBC_TEAM_LEVEL, "rnd": current_round}).mappings().all()

    last_week = conn.execute(sa_text("""
        SELECT MAX(start_week) FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
          AND conference = 'WBC' AND round = :rnd
    """), {"lyid": league_year_id, "level": WBC_TEAM_LEVEL, "rnd": current_round}).scalar()
    next_week = int(last_week) + 1

    created = []

    if next_round == "SF":
        # Pair QF winners: 1v4, 2v3
        if len(winners) == 4:
            sf_pairs = [(0, 3), (1, 2)]
        elif len(winners) == 2:
            sf_pairs = [(0, 1)]
        else:
            return {"error": f"Expected 4 or 2 QF winners, got {len(winners)}"}

        for snum, (i, j) in enumerate(sf_pairs, start=1):
            t_a = int(winners[i]["winner_team_id"])
            t_b = int(winners[j]["winner_team_id"])

            conn.execute(sa_text("""
                INSERT INTO playoff_series
                    (league_year_id, league_level, round, series_number,
                     team_a_id, team_b_id, seed_a, seed_b,
                     series_length, status, start_week, conference)
                VALUES
                    (:lyid, :level, 'SF', :snum,
                     :team_a, :team_b, 1, 2,
                     1, 'pending', :week, 'WBC')
            """), {
                "lyid": league_year_id, "level": WBC_TEAM_LEVEL,
                "snum": snum, "team_a": t_a, "team_b": t_b,
                "week": next_week,
            })

            add_series(
                engine, league_year=league_year, league_level=WBC_TEAM_LEVEL,
                home_team_id=t_a, away_team_id=t_b,
                week=next_week, games=1, game_type="wbc",
            )
            created.append({"round": "SF", "series_number": snum})

    elif next_round == "F":
        if len(winners) != 2:
            return {"error": f"Expected 2 SF winners, got {len(winners)}"}

        t_a = int(winners[0]["winner_team_id"])
        t_b = int(winners[1]["winner_team_id"])

        conn.execute(sa_text("""
            INSERT INTO playoff_series
                (league_year_id, league_level, round, series_number,
                 team_a_id, team_b_id, seed_a, seed_b,
                 series_length, status, start_week, conference)
            VALUES
                (:lyid, :level, 'F', 1,
                 :team_a, :team_b, 1, 2,
                 1, 'pending', :week, 'WBC')
        """), {
            "lyid": league_year_id, "level": WBC_TEAM_LEVEL,
            "team_a": t_a, "team_b": t_b,
            "week": next_week,
        })

        add_series(
            engine, league_year=league_year, league_level=WBC_TEAM_LEVEL,
            home_team_id=t_a, away_team_id=t_b,
            week=next_week, games=1, game_type="wbc",
        )
        created.append({"round": "F"})

    return {"round_advanced": next_round, "series_created": created, "week": next_week}


# =====================================================================
# Cleanup
# =====================================================================

def cleanup_wbc(conn, event_id: int) -> Dict[str, Any]:
    """
    Clean up after WBC completion:
    - Delete virtual team rows (team_level=99)
    - Mark event complete
    """
    import json

    event = conn.execute(sa_text("""
        SELECT * FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()

    if not event:
        return {"error": "Event not found"}

    meta = json.loads(event["metadata_json"] or "{}")
    team_map = meta.get("team_map", {})
    team_ids = list(team_map.values())

    if team_ids:
        placeholders = ",".join(str(tid) for tid in team_ids)
        # Delete dependent rows first (FK constraints)
        conn.execute(sa_text(f"""
            DELETE FROM game_results
            WHERE (home_team_id IN ({placeholders}) OR away_team_id IN ({placeholders}))
              AND game_type = 'wbc'
        """))
        conn.execute(sa_text(f"""
            DELETE FROM gamelist
            WHERE (home_team IN ({placeholders}) OR away_team IN ({placeholders}))
              AND game_type = 'wbc'
        """))
        conn.execute(sa_text(f"""
            DELETE FROM playoff_series
            WHERE (team_a_id IN ({placeholders}) OR team_b_id IN ({placeholders}))
              AND league_level = :level
        """), {"level": WBC_TEAM_LEVEL})
        conn.execute(sa_text(f"""
            DELETE FROM special_event_rosters WHERE event_id = :eid
        """), {"eid": event_id})
        conn.execute(sa_text(f"""
            DELETE FROM wbc_teams WHERE event_id = :eid
        """), {"eid": event_id})
        conn.execute(sa_text(f"""
            DELETE FROM teams WHERE id IN ({placeholders}) AND team_level = :level
        """), {"level": WBC_TEAM_LEVEL})

    conn.execute(sa_text("""
        UPDATE special_events SET status = 'complete', completed_at = NOW()
        WHERE id = :eid
    """), {"eid": event_id})

    log.info("wbc: cleaned up event %d, removed %d virtual teams", event_id, len(team_ids))
    return {"cleaned_teams": len(team_ids)}


# =====================================================================
# Query
# =====================================================================

def get_wbc_teams(conn, event_id: int) -> List[Dict]:
    """Get all WBC teams for an event."""
    rows = conn.execute(sa_text("""
        SELECT * FROM wbc_teams WHERE event_id = :eid
        ORDER BY pool_group, pool_wins DESC
    """), {"eid": event_id}).mappings().all()

    return [{
        "country_name": r["country_name"],
        "country_code": r["country_code"],
        "pool_group": r["pool_group"],
        "pool_wins": int(r["pool_wins"]),
        "pool_losses": int(r["pool_losses"]),
        "eliminated": bool(r["eliminated"]),
        "seed": int(r["seed"]) if r["seed"] else None,
    } for r in rows]


def get_wbc_rosters(conn, event_id: int) -> Dict[str, List]:
    """Get rosters for all WBC teams."""
    rows = conn.execute(sa_text("""
        SELECT ser.team_label, ser.player_id, ser.position_code,
               p.firstName, p.lastName
        FROM special_event_rosters ser
        JOIN simbbPlayers p ON p.id = ser.player_id
        WHERE ser.event_id = :eid
        ORDER BY ser.team_label, ser.position_code
    """), {"eid": event_id}).mappings().all()

    rosters: Dict[str, List] = {}
    for r in rows:
        label = r["team_label"]
        rosters.setdefault(label, []).append({
            "player_id": int(r["player_id"]),
            "name": f"{r['firstName']} {r['lastName']}".strip(),
            "position": r["position_code"],
        })

    return rosters


# =====================================================================
# Helpers
# =====================================================================

def _country_code(country: str) -> str:
    """Generate a short code for a country name."""
    CODES = {
        "USA": "USA", "Japan": "JPN", "Korea": "KOR",
        "Dominican Republic": "DOM", "Cuba": "CUB", "Venezuela": "VEN",
        "Puerto Rico": "PUR", "Mexico": "MEX", "Canada": "CAN",
        "Colombia": "COL", "Panama": "PAN", "Netherlands": "NED",
        "Taiwan": "TPE", "Australia": "AUS", "Italy": "ITA",
        "Brazil": "BRA", "Germany": "GER", "Israel": "ISR",
        "Great Britain": "GBR", "South Africa": "RSA",
        "Nicaragua": "NCA", "Czech Republic": "CZE",
        "China": "CHN", "Philippines": "PHI",
    }
    return CODES.get(country, country[:3].upper())
