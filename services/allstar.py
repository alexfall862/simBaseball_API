# services/allstar.py
"""
All-Star Game: ad-hoc exhibition game with WAR-based roster selection.
Stats do NOT accumulate into season totals; stamina/injuries DO persist.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text

from db import get_engine

log = logging.getLogger("app")

# Position slots per conference roster (~26 players)
POSITION_SLOTS = {
    "C": 2, "1B": 1, "2B": 1, "3B": 1, "SS": 1,
    "LF": 1, "CF": 1, "RF": 1, "DH": 1,
    "SP": 5, "RP": 5,
}
# Total starters + reserves
ROSTER_SIZE = 26


def create_allstar_event(conn, league_year_id: int) -> Dict[str, Any]:
    """
    Create a new All-Star event and auto-generate rosters.
    Returns event_id and roster summary.
    """
    conn.execute(sa_text("""
        INSERT INTO special_events
            (league_year_id, event_type, status, created_at)
        VALUES
            (:lyid, 'allstar', 'setup', NOW())
    """), {"lyid": league_year_id})

    event_id = conn.execute(sa_text("SELECT LAST_INSERT_ID()")).scalar()

    rosters = generate_allstar_rosters(conn, event_id, league_year_id)

    conn.execute(sa_text("""
        UPDATE special_events SET status = 'roster_ready' WHERE id = :eid
    """), {"eid": event_id})

    log.info("allstar: created event %d with %d AL + %d NL players",
             event_id, len(rosters.get("AL", [])), len(rosters.get("NL", [])))

    return {
        "event_id": event_id,
        "league_year_id": league_year_id,
        "rosters": rosters,
    }


def generate_allstar_rosters(
    conn, event_id: int, league_year_id: int
) -> Dict[str, List[Dict]]:
    """
    Auto-select All-Star rosters by WAR for each conference (AL/NL).
    Picks top WAR players per position, then fills remaining slots with
    best available regardless of position.
    """
    rosters = {}

    for conf in ["AL", "NL"]:
        # Get top players by WAR for this conference
        players = _get_conference_war_leaders(conn, league_year_id, conf)

        # Fill position slots
        selected = []
        used_ids = set()

        # Group by position
        by_pos: Dict[str, List[Dict]] = {}
        for p in players:
            by_pos.setdefault(p["position"], []).append(p)

        # Fill each position slot
        starters = []
        for pos, count in POSITION_SLOTS.items():
            candidates = by_pos.get(pos, [])
            filled = 0
            for c in candidates:
                if c["player_id"] in used_ids:
                    continue
                is_starter = filled == 0  # First at each position is starter
                selected.append({**c, "is_starter": is_starter})
                used_ids.add(c["player_id"])
                filled += 1
                if filled >= count:
                    break

        # Fill remaining roster spots with best available WAR
        remaining_needed = ROSTER_SIZE - len(selected)
        for p in players:
            if remaining_needed <= 0:
                break
            if p["player_id"] not in used_ids:
                selected.append({**p, "is_starter": False})
                used_ids.add(p["player_id"])
                remaining_needed -= 1

        # Insert into special_event_rosters
        for p in selected:
            conn.execute(sa_text("""
                INSERT INTO special_event_rosters
                    (event_id, team_label, player_id, position_code,
                     is_starter, source)
                VALUES
                    (:eid, :label, :pid, :pos, :starter, 'auto')
            """), {
                "eid": event_id, "label": conf,
                "pid": p["player_id"], "pos": p["position"],
                "starter": 1 if p["is_starter"] else 0,
            })

        rosters[conf] = selected

    return rosters


def _get_conference_war_leaders(
    conn, league_year_id: int, conference: str
) -> List[Dict]:
    """
    Get players sorted by WAR for a given conference at MLB level (9).
    Returns simplified player dicts with position and WAR.
    """
    # Batting WAR candidates
    bat_sql = sa_text("""
        SELECT bs.player_id, p.firstName, p.lastName, p.ptype,
               tm.team_abbrev, tm.id AS team_id,
               bs.at_bats, bs.hits, bs.doubles_hit, bs.triples,
               bs.home_runs, bs.walks, bs.runs,
               bs.stolen_bases, bs.caught_stealing,
               fs.position_code
        FROM player_batting_stats bs
        JOIN simbbPlayers p ON p.id = bs.player_id
        JOIN teams tm ON tm.id = bs.team_id
        LEFT JOIN player_fielding_stats fs ON fs.player_id = bs.player_id
            AND fs.league_year_id = bs.league_year_id
            AND fs.team_id = bs.team_id
        WHERE bs.league_year_id = :lyid
          AND tm.team_level = 9
          AND tm.conference = :conf
          AND bs.at_bats >= 30
        ORDER BY fs.innings DESC
    """)
    bat_rows = conn.execute(bat_sql, {
        "lyid": league_year_id, "conf": conference,
    }).mappings().all()

    # League averages for WAR calc
    lg = conn.execute(sa_text("""
        SELECT
            SUM(bs.hits + bs.walks) AS lg_on_base,
            SUM(bs.at_bats + bs.walks) AS lg_pa,
            SUM(bs.hits + bs.doubles_hit + 2*bs.triples + 3*bs.home_runs) AS lg_tb,
            SUM(bs.at_bats) AS lg_ab,
            SUM(bs.runs) AS lg_runs
        FROM player_batting_stats bs
        JOIN teams tm ON tm.id = bs.team_id
        WHERE bs.league_year_id = :lyid AND tm.team_level = 9
    """), {"lyid": league_year_id}).mappings().first()

    lg_pa = float(lg["lg_pa"] or 1)
    lg_ab = float(lg["lg_ab"] or 1)
    lg_runs = float(lg["lg_runs"] or 1)
    lg_obp = float(lg["lg_on_base"] or 0) / lg_pa
    lg_slg = float(lg["lg_tb"] or 0) / lg_ab
    lg_ops = lg_obp + lg_slg
    pa_per_run = lg_pa / lg_runs if lg_runs > 0 else 25.0
    repl_ops = lg_ops * 0.80

    # Pitching league avg
    lg_pit = conn.execute(sa_text("""
        SELECT SUM(ps.earned_runs) AS lg_er,
               SUM(ps.innings_pitched_outs) AS lg_ipo
        FROM player_pitching_stats ps
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid AND tm.team_level = 9
    """), {"lyid": league_year_id}).mappings().first()

    lg_ipo = float(lg_pit["lg_ipo"] or 1)
    lg_er = float(lg_pit["lg_er"] or 0)
    lg_era = lg_er * 27.0 / lg_ipo if lg_ipo > 0 else 4.50
    repl_era = lg_era / 0.80

    players = {}

    # Build position player WAR
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
            "type": "position",
        }

    # Pitcher WAR
    pit_sql = sa_text("""
        SELECT ps.player_id, p.firstName, p.lastName,
               tm.team_abbrev, tm.id AS team_id,
               ps.innings_pitched_outs, ps.earned_runs, ps.games_started
        FROM player_pitching_stats ps
        JOIN simbbPlayers p ON p.id = ps.player_id
        JOIN teams tm ON tm.id = ps.team_id
        WHERE ps.league_year_id = :lyid
          AND tm.team_level = 9
          AND tm.conference = :conf
          AND ps.innings_pitched_outs >= 30
    """)
    pit_rows = conn.execute(pit_sql, {
        "lyid": league_year_id, "conf": conference,
    }).mappings().all()

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
            players[pid]["type"] = "two-way"
        else:
            players[pid] = {
                "player_id": pid,
                "name": f"{row['firstName']} {row['lastName']}".strip(),
                "team_abbrev": row["team_abbrev"],
                "team_id": int(row["team_id"]),
                "position": pos,
                "war": round(war, 2),
                "type": "pitcher",
            }

    # Sort by WAR descending
    return sorted(players.values(), key=lambda p: p["war"], reverse=True)


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
                ON DUPLICATE KEY UPDATE
                    team_label = :label,
                    position_code = :pos,
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
            WHERE c.status = 'active' AND tm.team_level = 9
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
    """Get results for a completed All-Star game."""
    event = conn.execute(sa_text("""
        SELECT * FROM special_events WHERE id = :eid
    """), {"eid": event_id}).mappings().first()

    if not event:
        return None

    # Find the game result
    game = conn.execute(sa_text("""
        SELECT gr.* FROM game_results gr
        JOIN gamelist gl ON gl.id = gr.game_id
        WHERE gl.game_type = 'allstar'
          AND gr.season = (
              SELECT s.id FROM seasons s
              JOIN league_years ly ON ly.league_year = s.year
              WHERE ly.id = :lyid LIMIT 1
          )
        ORDER BY gr.completed_at DESC LIMIT 1
    """), {"lyid": int(event["league_year_id"])}).mappings().first()

    rosters = get_event_rosters(conn, event_id)

    return {
        "event_id": event_id,
        "status": event["status"],
        "game_result": dict(game) if game else None,
        "rosters": rosters["rosters"],
    }
