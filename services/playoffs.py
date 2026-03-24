# services/playoffs.py
"""
Playoff bracket generation, series tracking, and round advancement for:
  - MLB (level 9): 12-team bracket (3 div winners + 3 WC per league)
  - Minor Leagues (levels 5-8): Top 8 by record, single-elimination Bo7
  - College World Series (level 3): Conference champs + at-large, double-elimination
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text as sa_text

from db import get_engine

log = logging.getLogger("app")

# ---------------------------------------------------------------------------
# Home-field patterns: index = game number (0-based) → True if higher seed hosts
# ---------------------------------------------------------------------------
HOME_PATTERNS = {
    3: [True, True, True],                                  # Bo3: higher seed all
    5: [True, True, False, False, True],                    # Bo5: 2-2-1
    7: [True, True, False, False, False, True, True],       # Bo7: 2-3-2
}

# MLB playoff round progression
MLB_ROUNDS = ["WC", "DS", "CS", "WS"]

# Wins needed to clinch by series length
CLINCH = {3: 2, 5: 3, 7: 4}

# ---------------------------------------------------------------------------
# CWS double-elimination bracket (8 teams)
# ---------------------------------------------------------------------------
CWS_ROUND_ORDER = [
    "CWS_W1", "CWS_W2", "CWS_L1", "CWS_W3", "CWS_L2",
    "CWS_L3", "CWS_L4", "CWS_F1", "CWS_F2",
]

# Each transition: (prerequisite rounds that must ALL be complete, target round)
CWS_TRANSITIONS = [
    (["CWS_W1"],            "CWS_W2"),   # W1 winners play W2
    (["CWS_W1"],            "CWS_L1"),   # W1 losers play L1
    (["CWS_W2", "CWS_L1"], "CWS_W3"),   # W2 winners play winners final
    (["CWS_W2", "CWS_L1"], "CWS_L2"),   # CROSSOVER: W2 losers vs L1 winners
    (["CWS_L2"],            "CWS_L3"),   # L2 winners play each other
    (["CWS_W3", "CWS_L3"], "CWS_L4"),   # CROSSOVER: W3 loser vs L3 winner
    (["CWS_L4"],            "CWS_F1"),   # Losers bracket survivor vs W3 winner
    (["CWS_F1"],            "CWS_F2"),   # If-necessary (conditional)
]


# =====================================================================
# Helpers — game generation
# =====================================================================

def _create_game_1_for_series(
    engine, conn, league_year_id: int, league_level: int,
    team_a_id: int, team_b_id: int,
    series_length: int, start_week: int,
) -> None:
    """
    Insert only game 1 of a series into gamelist.
    Subsequent games are created by generate_next_series_game() after each result.
    """
    if series_length == 1:
        home, away = team_a_id, team_b_id
    else:
        pattern = HOME_PATTERNS[series_length]
        home = team_a_id if pattern[0] else team_b_id
        away = team_b_id if pattern[0] else team_a_id

    # Find first available subweek slot on start_week
    week, subweek = _next_available_subweek(
        conn, league_year_id, league_level,
        team_a_id, team_b_id, start_week,
    )

    _insert_single_playoff_game(
        conn, league_year_id, league_level,
        home, away, week, subweek,
    )


def generate_next_series_game(conn, series_id: int) -> Optional[Dict[str, Any]]:
    """
    After a series game is played and update_series_after_game has run,
    generate the next game if the series is still active (not clinched).

    Returns info about the created game, or None if the series is complete
    or no more games are needed.
    """
    series = conn.execute(sa_text("""
        SELECT id, league_year_id, league_level, round, series_number,
               team_a_id, team_b_id, seed_a, seed_b,
               wins_a, wins_b, series_length, status, start_week
        FROM playoff_series WHERE id = :sid
    """), {"sid": series_id}).mappings().first()

    if not series or series["status"] == "complete":
        return None

    series_len = int(series["series_length"])
    wins_a = int(series["wins_a"])
    wins_b = int(series["wins_b"])
    games_played = wins_a + wins_b

    # Single-game series — no next game
    if series_len == 1:
        return None

    # Already clinched?
    if wins_a >= CLINCH[series_len] or wins_b >= CLINCH[series_len]:
        return None

    # Determine game number (0-based) for the NEXT game
    game_idx = games_played  # next game is the one after all played games
    if game_idx >= series_len:
        return None  # shouldn't happen, but safety check

    # Determine home/away from the pattern
    pattern = HOME_PATTERNS[series_len]
    team_a_id = int(series["team_a_id"])
    team_b_id = int(series["team_b_id"])

    if pattern[game_idx]:
        home, away = team_a_id, team_b_id
    else:
        home, away = team_b_id, team_a_id

    # Determine week and subweek: each game in the series goes on the next
    # available subweek slot (a→b→c→d, then spill to next week).
    start_week = int(series["start_week"])
    league_year_id = int(series["league_year_id"])
    league_level = int(series["league_level"])

    # Find the next free subweek slot for this series' teams
    week, subweek = _next_available_subweek(
        conn, league_year_id, league_level,
        team_a_id, team_b_id, start_week,
    )

    _insert_single_playoff_game(
        conn, league_year_id, league_level,
        home, away, week, subweek,
    )

    log.info(
        "playoffs: generated game %d for series %d (%s), week %d, %d @ %d",
        game_idx + 1, series_id, series["round"], week, away, home,
    )

    return {
        "series_id": series_id,
        "game_number": game_idx + 1,
        "home_team_id": home,
        "away_team_id": away,
        "week": week,
    }


# =====================================================================
# MLB Playoffs (Level 9)
# =====================================================================

def determine_mlb_playoff_field(conn, league_year_id: int) -> Dict[str, List[Dict]]:
    """
    Determine the 12-team MLB playoff field (6 per league).

    Returns:
        {"AL": [seed_1..seed_6], "NL": [seed_1..seed_6]}
        Each entry: {seed, team_id, team_abbrev, conference, division, wins, losses, win_pct, qualifier}
    """
    sql = sa_text("""
        SELECT
            t.id AS team_id,
            t.team_abbrev,
            t.conference,
            t.division,
            COALESCE(w.wins, 0) AS wins,
            COALESCE(l.losses, 0) AS losses
        FROM teams t
        LEFT JOIN (
            SELECT winning_team_id, COUNT(*) AS wins
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid
                LIMIT 1
            ) AND game_type = 'regular'
            GROUP BY winning_team_id
        ) w ON w.winning_team_id = t.id
        LEFT JOIN (
            SELECT losing_team_id, COUNT(*) AS losses
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid
                LIMIT 1
            ) AND game_type = 'regular'
            GROUP BY losing_team_id
        ) l ON l.losing_team_id = t.id
        WHERE t.team_level = 9
        ORDER BY t.conference, COALESCE(w.wins, 0) DESC
    """)

    rows = conn.execute(sql, {"lyid": league_year_id}).mappings().all()

    # Group by conference → division
    conferences: Dict[str, Dict[str, List[Dict]]] = {}
    for r in rows:
        conf = r["conference"]
        div = r["division"]
        total = r["wins"] + r["losses"]
        entry = {
            "team_id": int(r["team_id"]),
            "team_abbrev": r["team_abbrev"],
            "conference": conf,
            "division": div,
            "wins": int(r["wins"]),
            "losses": int(r["losses"]),
            "win_pct": round(r["wins"] / total, 3) if total > 0 else 0.0,
        }
        conferences.setdefault(conf, {}).setdefault(div, []).append(entry)

    field = {}
    for conf, divisions in conferences.items():
        # Find division winners (best record per division)
        div_winners = []
        remaining = []
        for div_name, teams in divisions.items():
            teams.sort(key=lambda x: x["win_pct"], reverse=True)
            winner = teams[0]
            winner["qualifier"] = f"div_winner_{div_name}"
            div_winners.append(winner)
            remaining.extend(teams[1:])

        # Sort division winners by record (best record = seed 1)
        div_winners.sort(key=lambda x: x["win_pct"], reverse=True)

        # Wild cards: top 3 remaining by record
        remaining.sort(key=lambda x: x["win_pct"], reverse=True)
        wild_cards = remaining[:3]
        for wc in wild_cards:
            wc["qualifier"] = "wild_card"

        # Assign seeds 1-6
        seeded = div_winners + wild_cards
        for i, team in enumerate(seeded):
            team["seed"] = i + 1

        field[conf] = seeded

    return field


def create_mlb_bracket(
    conn,
    league_year_id: int,
    field: Dict[str, List[Dict]],
    start_week: int = 53,
) -> Dict[str, Any]:
    """
    Create Wild Card Series matchups and insert playoff_series + gamelist rows.
    WC: Seed 3v6, 4v5 per conference. Bo3, higher seed hosts all.

    Returns summary of created series.
    """
    engine = get_engine()
    created = []

    for conf in ["AL", "NL"]:
        seeds = {t["seed"]: t for t in field[conf]}

        # WC matchups: 3v6, 4v5
        matchups = [(3, 6), (4, 5)]
        for series_num, (seed_a, seed_b) in enumerate(matchups, start=1):
            team_a = seeds[seed_a]
            team_b = seeds[seed_b]

            # Insert playoff_series row
            conn.execute(sa_text("""
                INSERT INTO playoff_series
                    (league_year_id, league_level, round, series_number,
                     team_a_id, team_b_id, seed_a, seed_b,
                     series_length, status, start_week, conference)
                VALUES
                    (:lyid, 9, 'WC', :snum,
                     :team_a, :team_b, :seed_a, :seed_b,
                     3, 'pending', :week, :conf)
            """), {
                "lyid": league_year_id, "snum": series_num,
                "team_a": team_a["team_id"], "team_b": team_b["team_id"],
                "seed_a": seed_a, "seed_b": seed_b,
                "week": start_week, "conf": conf,
            })

            # Generate only game 1 — subsequent games created after each result
            _create_game_1_for_series(
                engine, conn, league_year_id, 9,
                team_a["team_id"], team_b["team_id"],
                series_length=3, start_week=start_week,
            )

            created.append({
                "round": "WC",
                "conference": conf,
                "matchup": f"{team_a['team_abbrev']} (#{seed_a}) vs {team_b['team_abbrev']} (#{seed_b})",
                "series_length": 3,
                "week": start_week,
            })

    # Seeds 1 and 2 get byes — DS matchups created after WC completes
    log.info("playoffs: created %d WC series for league_year %d", len(created), league_year_id)
    return {"series_created": created, "next_round": "DS", "next_week": start_week + 1}


def update_series_after_game(conn, game_id: int) -> Optional[Dict[str, Any]]:
    """
    After a playoff game completes, update the corresponding series win counts.
    If the series is still active, automatically generates the next game.
    If the series is clinched, marks it complete.

    Returns series status dict if found, None if game is not a playoff game.
    """
    # Get game info from game_results
    game_row = conn.execute(sa_text("""
        SELECT game_id, home_team_id, away_team_id, winning_team_id, game_type
        FROM game_results WHERE game_id = :gid
    """), {"gid": game_id}).mappings().first()

    if not game_row or game_row["game_type"] != "playoff":
        return None

    winning_tid = int(game_row["winning_team_id"])

    # Find the playoff_series this game belongs to
    series = conn.execute(sa_text("""
        SELECT id, team_a_id, team_b_id, wins_a, wins_b, series_length, status
        FROM playoff_series
        WHERE status IN ('pending', 'active')
          AND (team_a_id = :home OR team_a_id = :away)
          AND (team_b_id = :home OR team_b_id = :away)
        LIMIT 1
    """), {
        "home": int(game_row["home_team_id"]),
        "away": int(game_row["away_team_id"]),
    }).mappings().first()

    if not series:
        log.warning("playoffs: no active series found for game %d", game_id)
        return None

    series_id = int(series["id"])
    team_a_id = int(series["team_a_id"])
    wins_a = int(series["wins_a"])
    wins_b = int(series["wins_b"])
    series_len = int(series["series_length"])

    if winning_tid == team_a_id:
        wins_a += 1
    else:
        wins_b += 1

    clinch_target = CLINCH.get(series_len, 1)
    winner_id = None
    status = "active"

    if wins_a >= clinch_target:
        winner_id = team_a_id
        status = "complete"
    elif wins_b >= clinch_target:
        winner_id = int(series["team_b_id"])
        status = "complete"

    conn.execute(sa_text("""
        UPDATE playoff_series
        SET wins_a = :wa, wins_b = :wb, status = :status,
            winner_team_id = :winner
        WHERE id = :sid
    """), {
        "wa": wins_a, "wb": wins_b, "status": status,
        "winner": winner_id, "sid": series_id,
    })

    log.info(
        "playoffs: series %d updated: %d-%d, status=%s, winner=%s",
        series_id, wins_a, wins_b, status, winner_id,
    )

    result = {
        "series_id": series_id,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "status": status,
        "winner_team_id": winner_id,
        "next_game": None,
    }

    # Auto-generate the next game if the series is still active
    if status == "active":
        next_game = generate_next_series_game(conn, series_id)
        result["next_game"] = next_game

    return result


def advance_round(conn, league_year_id: int, league_level: int) -> Dict[str, Any]:
    """
    Check if the current round is complete and advance to the next round.
    Creates new playoff_series rows and gamelist entries for the next round.
    """
    engine = get_engine()

    # Find current round (most recent incomplete, or most recent complete)
    current = conn.execute(sa_text("""
        SELECT round, conference,
               COUNT(*) AS total,
               SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS done
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
        GROUP BY round, conference
        ORDER BY FIELD(round, 'WC', 'DS', 'CS', 'WS', 'QF', 'SF', 'F') DESC
        LIMIT 10
    """), {"lyid": league_year_id, "level": league_level}).mappings().all()

    if not current:
        return {"error": "No playoff series found"}

    # Find the latest round that's fully complete
    complete_rounds = {}
    for row in current:
        rnd = row["round"]
        complete_rounds.setdefault(rnd, {"total": 0, "done": 0})
        complete_rounds[rnd]["total"] += int(row["total"])
        complete_rounds[rnd]["done"] += int(row["done"])

    if league_level == 9:
        return _advance_mlb_round(conn, engine, league_year_id, complete_rounds)
    elif league_level == 3:
        return advance_cws_round(conn, league_year_id)
    else:
        return _advance_milb_round(conn, engine, league_year_id, league_level, complete_rounds)


def _advance_mlb_round(
    conn, engine, league_year_id: int, complete_rounds: Dict
) -> Dict[str, Any]:
    """Advance MLB playoffs to the next round."""

    # Determine which round just completed and needs advancement.
    # Walk rounds in order; find the latest complete round whose NEXT round
    # does not yet exist (i.e. hasn't been advanced into already).
    rnd = None
    next_round = None
    for i, r in enumerate(MLB_ROUNDS):
        info = complete_rounds.get(r)
        if not info or info["total"] != info["done"]:
            continue
        nxt_idx = i + 1
        if nxt_idx >= len(MLB_ROUNDS):
            return {"status": "complete", "message": "World Series is complete!"}
        candidate = MLB_ROUNDS[nxt_idx]
        if candidate not in complete_rounds:
            # Next round doesn't exist yet — this is the one to advance from
            rnd = r
            next_round = candidate
    if rnd is None:
        return {"error": "No fully complete round found to advance from"}

    # Get the last completed round's start week to calculate next week
    last_week_row = conn.execute(sa_text("""
        SELECT MAX(start_week) AS last_week FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 9 AND round = :rnd
    """), {"lyid": league_year_id, "rnd": rnd}).mappings().first()
    next_week = int(last_week_row["last_week"]) + 1

    # Get winners from the completed round
    winners = conn.execute(sa_text("""
        SELECT id, round, conference, winner_team_id, seed_a, seed_b,
               team_a_id, team_b_id
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 9
          AND round = :rnd AND status = 'complete'
        ORDER BY conference, series_number
    """), {"lyid": league_year_id, "rnd": rnd}).mappings().all()

    created = []

    if next_round == "DS":
        # DS: Seed 1 vs lowest remaining WC survivor, Seed 2 vs other
        # Get the original field seeds
        all_series = conn.execute(sa_text("""
            SELECT conference, seed_a, seed_b, winner_team_id, team_a_id
            FROM playoff_series
            WHERE league_year_id = :lyid AND league_level = 9
              AND round = 'WC' AND status = 'complete'
            ORDER BY conference, series_number
        """), {"lyid": league_year_id}).mappings().all()

        for conf in ["AL", "NL"]:
            # Get bye teams (seeds 1 and 2) from the field
            bye_teams = conn.execute(sa_text("""
                SELECT ps.team_a_id AS team_id, ps.seed_a AS seed
                FROM playoff_series ps
                WHERE ps.league_year_id = :lyid AND ps.league_level = 9
                  AND ps.round = 'WC' AND ps.conference = :conf
                UNION
                SELECT ps.team_b_id AS team_id, ps.seed_b AS seed
                FROM playoff_series ps
                WHERE ps.league_year_id = :lyid AND ps.league_level = 9
                  AND ps.round = 'WC' AND ps.conference = :conf
            """), {"lyid": league_year_id, "conf": conf}).mappings().all()

            # Actually, seeds 1 and 2 had byes - they aren't in WC series.
            # We need to get them from the original standings.
            # Let's query playoff_series for all conference info
            wc_winners = [
                s for s in all_series if s["conference"] == conf
            ]
            # WC winners carry the seed of the higher-seeded team in their series
            wc_winner_seeds = []
            for s in wc_winners:
                winner_tid = int(s["winner_team_id"])
                # Winner's seed is seed_a if they're team_a, else seed_b
                if winner_tid == int(s["team_a_id"]):
                    wc_winner_seeds.append((winner_tid, int(s["seed_a"])))
                else:
                    wc_winner_seeds.append((winner_tid, int(s["seed_b"])))

            # Sort by seed (higher seed number = lower seed)
            wc_winner_seeds.sort(key=lambda x: x[1])

            # Get bye teams (seeds 1 and 2) - they're in the field but NOT in WC series
            # Query teams table for seeds 1 and 2 from the field
            field = determine_mlb_playoff_field(conn, league_year_id)
            conf_field = {t["seed"]: t for t in field[conf]}

            seed_1 = conf_field[1]
            seed_2 = conf_field[2]

            # DS matchups:
            # Seed 1 vs lowest remaining seed (highest seed number among WC winners)
            # Seed 2 vs highest remaining seed (lowest seed number among WC winners)
            wc_winner_seeds.sort(key=lambda x: x[1], reverse=True)  # highest seed first
            lowest_remaining = wc_winner_seeds[0]  # highest seed number
            highest_remaining = wc_winner_seeds[1]  # lowest seed number

            ds_matchups = [
                (seed_1, lowest_remaining, 1),
                (seed_2, highest_remaining, 2),
            ]

            for top_seed, (opp_tid, opp_seed), snum in ds_matchups:
                conn.execute(sa_text("""
                    INSERT INTO playoff_series
                        (league_year_id, league_level, round, series_number,
                         team_a_id, team_b_id, seed_a, seed_b,
                         series_length, status, start_week, conference)
                    VALUES
                        (:lyid, 9, 'DS', :snum,
                         :team_a, :team_b, :seed_a, :seed_b,
                         5, 'pending', :week, :conf)
                """), {
                    "lyid": league_year_id, "snum": snum,
                    "team_a": top_seed["team_id"], "team_b": opp_tid,
                    "seed_a": top_seed["seed"], "seed_b": opp_seed,
                    "week": next_week, "conf": conf,
                })

                # Only game 1 — subsequent games auto-generated after each result
                _create_game_1_for_series(
                    engine, conn, league_year_id, 9,
                    top_seed["team_id"], opp_tid,
                    series_length=5, start_week=next_week,
                )

                created.append({
                    "round": "DS", "conference": conf,
                    "matchup": f"#{top_seed['seed']} vs #{opp_seed}",
                })

    elif next_round == "CS":
        # CS: DS winners within each conference
        for conf in ["AL", "NL"]:
            conf_winners = [
                w for w in winners if w["conference"] == conf
            ]
            if len(conf_winners) != 2:
                continue

            # Higher seed (lower number) is team_a
            w1 = conf_winners[0]
            w2 = conf_winners[1]

            # Determine seeds of winners
            s1 = min(int(w1["seed_a"]), int(w1["seed_b"]))
            s2 = min(int(w2["seed_a"]), int(w2["seed_b"]))
            if s1 > s2:
                w1, w2 = w2, w1
                s1, s2 = s2, s1

            conn.execute(sa_text("""
                INSERT INTO playoff_series
                    (league_year_id, league_level, round, series_number,
                     team_a_id, team_b_id, seed_a, seed_b,
                     series_length, status, start_week, conference)
                VALUES
                    (:lyid, 9, 'CS', 1,
                     :team_a, :team_b, :seed_a, :seed_b,
                     7, 'pending', :week, :conf)
            """), {
                "lyid": league_year_id,
                "team_a": int(w1["winner_team_id"]),
                "team_b": int(w2["winner_team_id"]),
                "seed_a": s1, "seed_b": s2,
                "week": next_week, "conf": conf,
            })

            _create_game_1_for_series(
                engine, conn, league_year_id, 9,
                int(w1["winner_team_id"]), int(w2["winner_team_id"]),
                series_length=7, start_week=next_week,
            )

            created.append({
                "round": "CS", "conference": conf,
                "matchup": f"#{s1} vs #{s2}",
            })

    elif next_round == "WS":
        # World Series: AL champ vs NL champ
        al_champ = [w for w in winners if w["conference"] == "AL"]
        nl_champ = [w for w in winners if w["conference"] == "NL"]

        if not al_champ or not nl_champ:
            return {"error": "Missing conference champion"}

        al = al_champ[0]
        nl = nl_champ[0]

        # Higher seed (better regular season record) gets home field
        al_seed = min(int(al["seed_a"]), int(al["seed_b"]))
        nl_seed = min(int(nl["seed_a"]), int(nl["seed_b"]))

        if al_seed <= nl_seed:
            team_a_id = int(al["winner_team_id"])
            team_b_id = int(nl["winner_team_id"])
        else:
            team_a_id = int(nl["winner_team_id"])
            team_b_id = int(al["winner_team_id"])

        conn.execute(sa_text("""
            INSERT INTO playoff_series
                (league_year_id, league_level, round, series_number,
                 team_a_id, team_b_id, seed_a, seed_b,
                 series_length, status, start_week, conference)
            VALUES
                (:lyid, 9, 'WS', 1,
                 :team_a, :team_b, :seed_a, :seed_b,
                 7, 'pending', :week, NULL)
        """), {
            "lyid": league_year_id,
            "team_a": team_a_id, "team_b": team_b_id,
            "seed_a": al_seed, "seed_b": nl_seed,
            "week": next_week,
        })

        _create_game_1_for_series(
            engine, conn, league_year_id, 9,
            team_a_id, team_b_id,
            series_length=7, start_week=next_week,
        )

        created.append({"round": "WS", "matchup": "AL champ vs NL champ"})

    return {"round_advanced": next_round, "series_created": created, "week": next_week}


# =====================================================================
# Minor League Playoffs (Levels 5-8)
# =====================================================================

def determine_milb_playoff_field(
    conn, league_year_id: int, league_level: int
) -> List[Dict]:
    """
    Top 8 teams by win percentage at the given minor league level.
    Returns list of 8 dicts sorted by seed (1=best record).
    """
    sql = sa_text("""
        SELECT
            t.id AS team_id,
            t.team_abbrev,
            COALESCE(w.wins, 0) AS wins,
            COALESCE(l.losses, 0) AS losses
        FROM teams t
        LEFT JOIN (
            SELECT winning_team_id, COUNT(*) AS wins
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid
                LIMIT 1
            ) AND game_type = 'regular' AND league_level = :level
            GROUP BY winning_team_id
        ) w ON w.winning_team_id = t.id
        LEFT JOIN (
            SELECT losing_team_id, COUNT(*) AS losses
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid
                LIMIT 1
            ) AND game_type = 'regular' AND league_level = :level
            GROUP BY losing_team_id
        ) l ON l.losing_team_id = t.id
        WHERE t.team_level = :level
        HAVING (wins + losses) > 0
        ORDER BY wins / (wins + losses) DESC
        LIMIT 8
    """)

    rows = conn.execute(sql, {"lyid": league_year_id, "level": league_level}).mappings().all()

    field = []
    for i, r in enumerate(rows):
        total = int(r["wins"]) + int(r["losses"])
        field.append({
            "seed": i + 1,
            "team_id": int(r["team_id"]),
            "team_abbrev": r["team_abbrev"],
            "wins": int(r["wins"]),
            "losses": int(r["losses"]),
            "win_pct": round(int(r["wins"]) / total, 3) if total > 0 else 0.0,
            "qualifier": "record",
        })

    return field


def create_milb_bracket(
    conn,
    league_year_id: int,
    league_level: int,
    field: List[Dict],
    start_week: int = 40,
) -> Dict[str, Any]:
    """
    Create quarterfinal matchups for minor league playoffs.
    QF: 1v8, 2v7, 3v6, 4v5 — all Bo7.
    """
    engine = get_engine()
    seeds = {t["seed"]: t for t in field}
    created = []

    matchups = [(1, 8), (2, 7), (3, 6), (4, 5)]
    for series_num, (seed_a, seed_b) in enumerate(matchups, start=1):
        team_a = seeds[seed_a]
        team_b = seeds[seed_b]

        conn.execute(sa_text("""
            INSERT INTO playoff_series
                (league_year_id, league_level, round, series_number,
                 team_a_id, team_b_id, seed_a, seed_b,
                 series_length, status, start_week, conference)
            VALUES
                (:lyid, :level, 'QF', :snum,
                 :team_a, :team_b, :seed_a, :seed_b,
                 7, 'pending', :week, NULL)
        """), {
            "lyid": league_year_id, "level": league_level, "snum": series_num,
            "team_a": team_a["team_id"], "team_b": team_b["team_id"],
            "seed_a": seed_a, "seed_b": seed_b,
            "week": start_week,
        })

        _create_game_1_for_series(
            engine, conn, league_year_id, league_level,
            team_a["team_id"], team_b["team_id"],
            series_length=7, start_week=start_week,
        )

        created.append({
            "round": "QF",
            "matchup": f"{team_a['team_abbrev']} (#{seed_a}) vs {team_b['team_abbrev']} (#{seed_b})",
        })

    return {"series_created": created, "next_round": "SF", "next_week": start_week + 2}


def _advance_milb_round(
    conn, engine, league_year_id: int, league_level: int,
    complete_rounds: Dict,
) -> Dict[str, Any]:
    """Advance minor league playoffs (QF→SF→F)."""
    MILB_ROUNDS = ["QF", "SF", "F"]

    rnd = None
    next_round = None
    for i, r in enumerate(MILB_ROUNDS):
        info = complete_rounds.get(r)
        if not info or info["total"] != info["done"]:
            continue
        nxt_idx = i + 1
        if nxt_idx >= len(MILB_ROUNDS):
            return {"status": "complete", "message": "Finals complete!"}
        candidate = MILB_ROUNDS[nxt_idx]
        if candidate not in complete_rounds:
            rnd = r
            next_round = candidate
    if rnd is None:
        return {"error": "No fully complete round found"}

    last_week_row = conn.execute(sa_text("""
        SELECT MAX(start_week) AS last_week FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level AND round = :rnd
    """), {"lyid": league_year_id, "level": league_level, "rnd": rnd}).mappings().first()
    next_week = int(last_week_row["last_week"]) + 2

    winners = conn.execute(sa_text("""
        SELECT winner_team_id, seed_a, seed_b, team_a_id
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
          AND round = :rnd AND status = 'complete'
        ORDER BY series_number
    """), {"lyid": league_year_id, "level": league_level, "rnd": rnd}).mappings().all()

    created = []

    if next_round == "SF":
        # SF: pair QF winners 1v4, 2v3
        if len(winners) != 4:
            return {"error": f"Expected 4 QF winners, got {len(winners)}"}

        sf_matchups = [(0, 3), (1, 2)]  # QF winners ordered by series_number
        for snum, (i, j) in enumerate(sf_matchups, start=1):
            w_a = winners[i]
            w_b = winners[j]
            a_seed = min(int(w_a["seed_a"]), int(w_a["seed_b"]))
            b_seed = min(int(w_b["seed_a"]), int(w_b["seed_b"]))

            # Higher seed (lower number) is team_a
            if a_seed > b_seed:
                w_a, w_b = w_b, w_a
                a_seed, b_seed = b_seed, a_seed

            conn.execute(sa_text("""
                INSERT INTO playoff_series
                    (league_year_id, league_level, round, series_number,
                     team_a_id, team_b_id, seed_a, seed_b,
                     series_length, status, start_week, conference)
                VALUES
                    (:lyid, :level, 'SF', :snum,
                     :team_a, :team_b, :seed_a, :seed_b,
                     7, 'pending', :week, NULL)
            """), {
                "lyid": league_year_id, "level": league_level, "snum": snum,
                "team_a": int(w_a["winner_team_id"]),
                "team_b": int(w_b["winner_team_id"]),
                "seed_a": a_seed, "seed_b": b_seed,
                "week": next_week,
            })

            _create_game_1_for_series(
                engine, conn, league_year_id, league_level,
                int(w_a["winner_team_id"]), int(w_b["winner_team_id"]),
                series_length=7, start_week=next_week,
            )

            created.append({"round": "SF", "matchup": f"#{a_seed} vs #{b_seed}"})

    elif next_round == "F":
        if len(winners) != 2:
            return {"error": f"Expected 2 SF winners, got {len(winners)}"}

        w_a = winners[0]
        w_b = winners[1]
        a_seed = min(int(w_a["seed_a"]), int(w_a["seed_b"]))
        b_seed = min(int(w_b["seed_a"]), int(w_b["seed_b"]))
        if a_seed > b_seed:
            w_a, w_b = w_b, w_a
            a_seed, b_seed = b_seed, a_seed

        conn.execute(sa_text("""
            INSERT INTO playoff_series
                (league_year_id, league_level, round, series_number,
                 team_a_id, team_b_id, seed_a, seed_b,
                 series_length, status, start_week, conference)
            VALUES
                (:lyid, :level, 'F', 1,
                 :team_a, :team_b, :seed_a, :seed_b,
                 7, 'pending', :week, NULL)
        """), {
            "lyid": league_year_id, "level": league_level,
            "team_a": int(w_a["winner_team_id"]),
            "team_b": int(w_b["winner_team_id"]),
            "seed_a": a_seed, "seed_b": b_seed,
            "week": next_week,
        })

        _create_game_1_for_series(
            engine, conn, league_year_id, league_level,
            int(w_a["winner_team_id"]), int(w_b["winner_team_id"]),
            series_length=7, start_week=next_week,
        )

        created.append({"round": "F", "matchup": f"#{a_seed} vs #{b_seed}"})

    return {"round_advanced": next_round, "series_created": created, "week": next_week}


# =====================================================================
# College World Series (Level 3) — Double Elimination
# =====================================================================

def determine_cws_field(conn, league_year_id: int) -> List[Dict]:
    """
    Determine CWS field: conference champions (best conf record per conference)
    plus at-large bids (best overall record) to fill remaining spots.
    Default: 8-team field.
    """
    # Get all college teams with records
    sql = sa_text("""
        SELECT
            t.id AS team_id,
            t.team_abbrev,
            t.conference,
            COALESCE(w.wins, 0) AS wins,
            COALESCE(l.losses, 0) AS losses,
            COALESCE(cw.conf_wins, 0) AS conf_wins,
            COALESCE(cl.conf_losses, 0) AS conf_losses
        FROM teams t
        LEFT JOIN (
            SELECT winning_team_id, COUNT(*) AS wins
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid LIMIT 1
            ) AND game_type = 'regular' AND league_level = 3
            GROUP BY winning_team_id
        ) w ON w.winning_team_id = t.id
        LEFT JOIN (
            SELECT losing_team_id, COUNT(*) AS losses
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid LIMIT 1
            ) AND game_type = 'regular' AND league_level = 3
            GROUP BY losing_team_id
        ) l ON l.losing_team_id = t.id
        LEFT JOIN (
            SELECT gr.winning_team_id, COUNT(*) AS conf_wins
            FROM game_results gr
            JOIN gamelist gl ON gl.id = gr.game_id
            WHERE gr.season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid LIMIT 1
            ) AND gr.game_type = 'regular' AND gl.is_conference = 1
            GROUP BY gr.winning_team_id
        ) cw ON cw.winning_team_id = t.id
        LEFT JOIN (
            SELECT gr.losing_team_id, COUNT(*) AS conf_losses
            FROM game_results gr
            JOIN gamelist gl ON gl.id = gr.game_id
            WHERE gr.season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid LIMIT 1
            ) AND gr.game_type = 'regular' AND gl.is_conference = 1
            GROUP BY gr.losing_team_id
        ) cl ON cl.losing_team_id = t.id
        WHERE t.team_level = 3
        HAVING (wins + losses) > 0
    """)

    rows = conn.execute(sql, {"lyid": league_year_id}).mappings().all()

    # Find conference champions
    by_conf: Dict[str, List[Dict]] = {}
    for r in rows:
        conf = r["conference"] or "Independent"
        total_conf = int(r["conf_wins"]) + int(r["conf_losses"])
        total = int(r["wins"]) + int(r["losses"])
        entry = {
            "team_id": int(r["team_id"]),
            "team_abbrev": r["team_abbrev"],
            "conference": conf,
            "wins": int(r["wins"]),
            "losses": int(r["losses"]),
            "win_pct": round(int(r["wins"]) / total, 3) if total > 0 else 0.0,
            "conf_wins": int(r["conf_wins"]),
            "conf_losses": int(r["conf_losses"]),
            "conf_win_pct": round(int(r["conf_wins"]) / total_conf, 3) if total_conf > 0 else 0.0,
        }
        by_conf.setdefault(conf, []).append(entry)

    conf_champs = []
    used_ids = set()
    for conf, teams in by_conf.items():
        if conf == "Independent":
            continue
        teams.sort(key=lambda x: x["conf_win_pct"], reverse=True)
        champ = teams[0]
        champ["qualifier"] = "conf_champ"
        conf_champs.append(champ)
        used_ids.add(champ["team_id"])

    # Fill remaining spots with at-large bids (best overall record)
    at_large_pool = [
        entry for r in rows
        if (entry := {
            "team_id": int(r["team_id"]),
            "team_abbrev": r["team_abbrev"],
            "conference": r["conference"] or "Independent",
            "wins": int(r["wins"]),
            "losses": int(r["losses"]),
            "win_pct": round(int(r["wins"]) / (int(r["wins"]) + int(r["losses"])), 3)
                if (int(r["wins"]) + int(r["losses"])) > 0 else 0.0,
            "qualifier": "at_large",
        }) and int(r["team_id"]) not in used_ids
    ]
    at_large_pool.sort(key=lambda x: x["win_pct"], reverse=True)

    target_size = 8
    needed = target_size - len(conf_champs)
    at_large = at_large_pool[:max(0, needed)]

    # Combine and seed by overall record
    field = conf_champs + at_large
    field.sort(key=lambda x: x["win_pct"], reverse=True)
    for i, t in enumerate(field):
        t["seed"] = i + 1

    return field[:target_size]


def create_cws_bracket(
    conn,
    league_year_id: int,
    field: List[Dict],
    start_week: int = 35,
) -> Dict[str, Any]:
    """
    Create CWS bracket entries and first-round games.
    Double elimination: losers drop to losers bracket; 2 losses = eliminated.
    First round: 1v8, 2v7, 3v6, 4v5 — single games.
    """
    # Insert bracket entries
    for t in field:
        conn.execute(sa_text("""
            INSERT INTO cws_bracket
                (league_year_id, team_id, seed, qualification, losses,
                 eliminated, bracket_side)
            VALUES
                (:lyid, :tid, :seed, :qual, 0, 0, 'winners')
        """), {
            "lyid": league_year_id, "tid": t["team_id"],
            "seed": t["seed"], "qual": t["qualifier"],
        })

    # Create first-round single games (winners bracket)
    matchups = [(1, 8), (2, 7), (3, 6), (4, 5)]
    seeds = {t["seed"]: t for t in field}
    created = []

    for series_num, (seed_a, seed_b) in enumerate(matchups, start=1):
        team_a = seeds[seed_a]
        team_b = seeds[seed_b]

        conn.execute(sa_text("""
            INSERT INTO playoff_series
                (league_year_id, league_level, round, series_number,
                 team_a_id, team_b_id, seed_a, seed_b,
                 series_length, status, start_week, conference)
            VALUES
                (:lyid, 3, 'CWS_W1', :snum,
                 :team_a, :team_b, :seed_a, :seed_b,
                 1, 'pending', :week, NULL)
        """), {
            "lyid": league_year_id, "snum": series_num,
            "team_a": team_a["team_id"], "team_b": team_b["team_id"],
            "seed_a": seed_a, "seed_b": seed_b,
            "week": start_week,
        })

        # Single game — higher seed hosts, find available subweek
        week, subweek = _next_available_subweek(
            conn, league_year_id, 3,
            team_a["team_id"], team_b["team_id"], start_week,
        )
        _insert_single_playoff_game(
            conn, league_year_id, 3,
            team_a["team_id"], team_b["team_id"],
            week, subweek,
        )

        created.append({
            "round": "CWS_W1",
            "matchup": f"{team_a['team_abbrev']} (#{seed_a}) vs {team_b['team_abbrev']} (#{seed_b})",
        })

    return {"series_created": created, "bracket_size": len(field)}


# ---------------------------------------------------------------------------
# CWS helpers
# ---------------------------------------------------------------------------

def _cws_get_series_results(
    conn, league_year_id: int, round_name: str,
) -> List[Dict[str, Any]]:
    """
    Return winner/loser info for every completed series in *round_name*.
    Each dict: {winner_id, loser_id, winner_seed, loser_seed, series_number}
    """
    rows = conn.execute(sa_text("""
        SELECT series_number, team_a_id, team_b_id, seed_a, seed_b,
               winner_team_id
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
          AND round = :rnd AND status = 'complete'
        ORDER BY series_number
    """), {"lyid": league_year_id, "rnd": round_name}).mappings().all()

    results = []
    for r in rows:
        winner_id = int(r["winner_team_id"])
        a_id = int(r["team_a_id"])
        b_id = int(r["team_b_id"])
        if winner_id == a_id:
            loser_id = b_id
            winner_seed = int(r["seed_a"])
            loser_seed = int(r["seed_b"])
        else:
            loser_id = a_id
            winner_seed = int(r["seed_b"])
            loser_seed = int(r["seed_a"])
        results.append({
            "winner_id": winner_id,
            "loser_id": loser_id,
            "winner_seed": winner_seed,
            "loser_seed": loser_seed,
            "series_number": int(r["series_number"]),
        })
    return results


def _cws_update_bracket(
    conn, league_year_id: int, team_ids: List[int], *, eliminate: bool = False,
) -> None:
    """
    Demote teams in cws_bracket.
    - eliminate=False  → losses += 1, bracket_side = 'losers'
    - eliminate=True   → losses += 1, bracket_side = 'eliminated', eliminated = 1
    """
    if not team_ids:
        return
    for tid in team_ids:
        if eliminate:
            conn.execute(sa_text("""
                UPDATE cws_bracket
                SET losses = losses + 1, bracket_side = 'eliminated', eliminated = 1
                WHERE league_year_id = :lyid AND team_id = :tid
            """), {"lyid": league_year_id, "tid": tid})
        else:
            conn.execute(sa_text("""
                UPDATE cws_bracket
                SET losses = losses + 1, bracket_side = 'losers'
                WHERE league_year_id = :lyid AND team_id = :tid
                  AND eliminated = 0
            """), {"lyid": league_year_id, "tid": tid})


def _cws_create_series_and_game(
    conn, league_year_id: int, round_name: str, series_number: int,
    team_a_id: int, team_b_id: int, seed_a: int, seed_b: int,
    start_week: int,
) -> Dict[str, Any]:
    """Insert one CWS playoff_series (Bo1) and schedule the game."""
    conn.execute(sa_text("""
        INSERT INTO playoff_series
            (league_year_id, league_level, round, series_number,
             team_a_id, team_b_id, seed_a, seed_b,
             series_length, status, start_week, conference)
        VALUES
            (:lyid, 3, :rnd, :snum,
             :team_a, :team_b, :seed_a, :seed_b,
             1, 'pending', :week, NULL)
    """), {
        "lyid": league_year_id, "rnd": round_name, "snum": series_number,
        "team_a": team_a_id, "team_b": team_b_id,
        "seed_a": seed_a, "seed_b": seed_b,
        "week": start_week,
    })

    w, sw = _next_available_subweek(
        conn, league_year_id, 3, team_a_id, team_b_id, start_week,
    )
    _insert_single_playoff_game(conn, league_year_id, 3, team_a_id, team_b_id, w, sw)

    return {"round": round_name, "matchup": f"#{seed_a} vs #{seed_b}"}


def _cws_next_week(conn, league_year_id: int, prereq_rounds: List[str]) -> int:
    """Determine the start_week for a new CWS round (max prereq week + 1)."""
    placeholders = ", ".join(f":r{i}" for i in range(len(prereq_rounds)))
    params: Dict[str, Any] = {"lyid": league_year_id}
    for i, rnd in enumerate(prereq_rounds):
        params[f"r{i}"] = rnd
    row = conn.execute(sa_text(f"""
        SELECT MAX(start_week) AS mw FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
          AND round IN ({placeholders})
    """), params).mappings().first()
    return int(row["mw"]) + 1 if row and row["mw"] is not None else 35


def _cws_pair_by_seed(teams: List[Dict]) -> List[Tuple[Dict, Dict]]:
    """Sort teams by seed and pair best-vs-worst."""
    teams.sort(key=lambda t: t["seed"])
    pairs = []
    lo, hi = 0, len(teams) - 1
    while lo < hi:
        pairs.append((teams[lo], teams[hi]))
        lo += 1
        hi -= 1
    return pairs


# ---------------------------------------------------------------------------
# CWS builder functions (one per target round)
# ---------------------------------------------------------------------------

def _cws_build_w2(conn, lyid: int, prereqs: List[str]) -> List[Dict]:
    """W1 winners → W2 matchups.  Demote W1 losers to losers bracket."""
    results = _cws_get_series_results(conn, lyid, "CWS_W1")
    week = _cws_next_week(conn, lyid, prereqs)

    # Demote W1 losers
    _cws_update_bracket(conn, lyid, [r["loser_id"] for r in results])

    # W1 winners play W2
    winners = [{"team_id": r["winner_id"], "seed": r["winner_seed"]} for r in results]
    pairs = _cws_pair_by_seed(winners)

    created = []
    for snum, (t1, t2) in enumerate(pairs, start=1):
        info = _cws_create_series_and_game(
            conn, lyid, "CWS_W2", snum,
            t1["team_id"], t2["team_id"], t1["seed"], t2["seed"], week,
        )
        created.append(info)
    return created


def _cws_build_l1(conn, lyid: int, prereqs: List[str]) -> List[Dict]:
    """W1 losers (now in losers bracket) → L1 matchups."""
    results = _cws_get_series_results(conn, lyid, "CWS_W1")
    week = _cws_next_week(conn, lyid, prereqs)

    losers = [{"team_id": r["loser_id"], "seed": r["loser_seed"]} for r in results]
    pairs = _cws_pair_by_seed(losers)

    created = []
    for snum, (t1, t2) in enumerate(pairs, start=1):
        info = _cws_create_series_and_game(
            conn, lyid, "CWS_L1", snum,
            t1["team_id"], t2["team_id"], t1["seed"], t2["seed"], week,
        )
        created.append(info)
    return created


def _cws_build_w3(conn, lyid: int, prereqs: List[str]) -> List[Dict]:
    """W2 winners → winners bracket final."""
    results = _cws_get_series_results(conn, lyid, "CWS_W2")
    week = _cws_next_week(conn, lyid, prereqs)

    winners = [{"team_id": r["winner_id"], "seed": r["winner_seed"]} for r in results]
    winners.sort(key=lambda t: t["seed"])
    t1, t2 = winners[0], winners[1]

    return [_cws_create_series_and_game(
        conn, lyid, "CWS_W3", 1,
        t1["team_id"], t2["team_id"], t1["seed"], t2["seed"], week,
    )]


def _cws_build_l2(conn, lyid: int, prereqs: List[str]) -> List[Dict]:
    """CROSSOVER: W2 losers (dropping down) vs L1 winners."""
    w2_results = _cws_get_series_results(conn, lyid, "CWS_W2")
    l1_results = _cws_get_series_results(conn, lyid, "CWS_L1")
    week = _cws_next_week(conn, lyid, prereqs)

    # Demote W2 losers to losers bracket
    _cws_update_bracket(conn, lyid, [r["loser_id"] for r in w2_results])
    # Eliminate L1 losers (second loss)
    _cws_update_bracket(conn, lyid, [r["loser_id"] for r in l1_results], eliminate=True)

    # Crossover pairing: W2 losers vs L1 winners, matched by seed
    w2_losers = [{"team_id": r["loser_id"], "seed": r["loser_seed"]} for r in w2_results]
    l1_winners = [{"team_id": r["winner_id"], "seed": r["winner_seed"]} for r in l1_results]
    w2_losers.sort(key=lambda t: t["seed"])
    l1_winners.sort(key=lambda t: t["seed"], reverse=True)

    created = []
    for snum, (drop, surv) in enumerate(zip(w2_losers, l1_winners), start=1):
        # Higher seed (lower number) is team_a
        if drop["seed"] < surv["seed"]:
            a, b = drop, surv
        else:
            a, b = surv, drop
        info = _cws_create_series_and_game(
            conn, lyid, "CWS_L2", snum,
            a["team_id"], b["team_id"], a["seed"], b["seed"], week,
        )
        created.append(info)
    return created


def _cws_build_l3(conn, lyid: int, prereqs: List[str]) -> List[Dict]:
    """L2 winners play each other.  Eliminate L2 losers."""
    results = _cws_get_series_results(conn, lyid, "CWS_L2")
    week = _cws_next_week(conn, lyid, prereqs)

    # Eliminate L2 losers (second loss)
    _cws_update_bracket(conn, lyid, [r["loser_id"] for r in results], eliminate=True)

    winners = [{"team_id": r["winner_id"], "seed": r["winner_seed"]} for r in results]
    winners.sort(key=lambda t: t["seed"])
    t1, t2 = winners[0], winners[1]

    return [_cws_create_series_and_game(
        conn, lyid, "CWS_L3", 1,
        t1["team_id"], t2["team_id"], t1["seed"], t2["seed"], week,
    )]


def _cws_build_l4(conn, lyid: int, prereqs: List[str]) -> List[Dict]:
    """CROSSOVER: W3 loser (dropping down) vs L3 winner."""
    w3_results = _cws_get_series_results(conn, lyid, "CWS_W3")
    l3_results = _cws_get_series_results(conn, lyid, "CWS_L3")
    week = _cws_next_week(conn, lyid, prereqs)

    # Demote W3 loser to losers bracket
    _cws_update_bracket(conn, lyid, [r["loser_id"] for r in w3_results])
    # Eliminate L3 loser (second loss)
    _cws_update_bracket(conn, lyid, [r["loser_id"] for r in l3_results], eliminate=True)

    w3_loser = w3_results[0]
    l3_winner = l3_results[0]
    drop = {"team_id": w3_loser["loser_id"], "seed": w3_loser["loser_seed"]}
    surv = {"team_id": l3_winner["winner_id"], "seed": l3_winner["winner_seed"]}

    if drop["seed"] < surv["seed"]:
        a, b = drop, surv
    else:
        a, b = surv, drop

    return [_cws_create_series_and_game(
        conn, lyid, "CWS_L4", 1,
        a["team_id"], b["team_id"], a["seed"], b["seed"], week,
    )]


def _cws_build_f1(conn, lyid: int, prereqs: List[str]) -> List[Dict]:
    """Championship: W3 winner (undefeated) vs L4 winner (losers bracket survivor).
    Convention: team_a = W3 winner so F2 conditional can check easily."""
    w3_results = _cws_get_series_results(conn, lyid, "CWS_W3")
    l4_results = _cws_get_series_results(conn, lyid, "CWS_L4")
    week = _cws_next_week(conn, lyid, prereqs)

    # Eliminate L4 loser (second loss)
    _cws_update_bracket(conn, lyid, [r["loser_id"] for r in l4_results], eliminate=True)

    undefeated = w3_results[0]
    survivor = l4_results[0]
    team_a = {"team_id": undefeated["winner_id"], "seed": undefeated["winner_seed"]}
    team_b = {"team_id": survivor["winner_id"], "seed": survivor["winner_seed"]}

    # team_a is always the undefeated side (for F2 conditional check)
    return [_cws_create_series_and_game(
        conn, lyid, "CWS_F1", 1,
        team_a["team_id"], team_b["team_id"],
        team_a["seed"], team_b["seed"], week,
    )]


def _cws_build_f2(conn, lyid: int, prereqs: List[str]) -> List[Dict]:
    """If-necessary game: only created if the losers bracket team won F1."""
    f1_series = conn.execute(sa_text("""
        SELECT team_a_id, team_b_id, winner_team_id
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
          AND round = 'CWS_F1' AND status = 'complete'
        LIMIT 1
    """), {"lyid": lyid}).mappings().first()

    if not f1_series:
        return []

    winner_id = int(f1_series["winner_team_id"])
    team_a_id = int(f1_series["team_a_id"])  # the undefeated side

    if winner_id == team_a_id:
        # Undefeated team won — tournament is complete, no F2 needed
        # Eliminate the loser
        loser_id = int(f1_series["team_b_id"])
        _cws_update_bracket(conn, lyid, [loser_id], eliminate=True)
        return []

    # Losers bracket team won F1 — need an if-necessary game
    # The undefeated team just got its first loss
    _cws_update_bracket(conn, lyid, [team_a_id])

    week = _cws_next_week(conn, lyid, prereqs)
    # Get seeds from cws_bracket
    seeds = {}
    for tid in [team_a_id, winner_id]:
        row = conn.execute(sa_text("""
            SELECT seed FROM cws_bracket
            WHERE league_year_id = :lyid AND team_id = :tid
        """), {"lyid": lyid, "tid": tid}).first()
        seeds[tid] = int(row[0]) if row else 0

    return [_cws_create_series_and_game(
        conn, lyid, "CWS_F2", 1,
        team_a_id, winner_id,
        seeds[team_a_id], seeds[winner_id], week,
    )]


# Map target round → builder function
_CWS_BUILDERS: Dict[str, Any] = {
    "CWS_W2": _cws_build_w2,
    "CWS_L1": _cws_build_l1,
    "CWS_W3": _cws_build_w3,
    "CWS_L2": _cws_build_l2,
    "CWS_L3": _cws_build_l3,
    "CWS_L4": _cws_build_l4,
    "CWS_F1": _cws_build_f1,
    "CWS_F2": _cws_build_f2,
}


# ---------------------------------------------------------------------------
# CWS state-machine advancement
# ---------------------------------------------------------------------------

def advance_cws_round(conn, league_year_id: int) -> Dict[str, Any]:
    """
    Advance the CWS double-elimination bracket.

    Uses a state-machine approach: iterates CWS_TRANSITIONS, checks whether
    all prerequisite rounds are complete and the target round doesn't already
    exist, then fires all actionable transitions in a single call.

    Idempotency: if the target round already has playoff_series rows, the
    transition is skipped (safe to call repeatedly).
    """
    # Load all existing CWS rounds and their completion status
    all_series = conn.execute(sa_text("""
        SELECT round, status FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
          AND round LIKE 'CWS_%%'
    """), {"lyid": league_year_id}).mappings().all()

    if not all_series:
        return {"error": "No CWS series found"}

    # Build {round_name: {total, complete}} map
    round_status: Dict[str, Dict[str, int]] = {}
    for s in all_series:
        rnd = s["round"]
        round_status.setdefault(rnd, {"total": 0, "complete": 0})
        round_status[rnd]["total"] += 1
        if s["status"] == "complete":
            round_status[rnd]["complete"] += 1

    def _round_complete(rnd: str) -> bool:
        info = round_status.get(rnd)
        return info is not None and info["total"] == info["complete"]

    created_all: List[Dict] = []

    for prereqs, target in CWS_TRANSITIONS:
        # Skip if target round already exists (idempotency)
        if target in round_status:
            continue
        # Skip if any prerequisite is missing or incomplete
        if not all(_round_complete(p) for p in prereqs):
            continue

        # Fire this transition
        builder = _CWS_BUILDERS[target]
        created = builder(conn, league_year_id, prereqs)
        created_all.extend(created)

        # Register the new round so later transitions can see it
        # (even if empty, e.g. F2 not needed — marks the transition as processed)
        round_status[target] = {"total": len(created), "complete": 0}

        log.info(
            "CWS advance: created %d series for %s (prereqs: %s)",
            len(created), target, prereqs,
        )

    if not created_all:
        # Check if tournament is complete (1 or fewer non-eliminated teams)
        remaining = conn.execute(sa_text("""
            SELECT COUNT(*) AS cnt FROM cws_bracket
            WHERE league_year_id = :lyid AND eliminated = 0
        """), {"lyid": league_year_id}).scalar()

        if remaining <= 1:
            champion = conn.execute(sa_text("""
                SELECT team_id FROM cws_bracket
                WHERE league_year_id = :lyid AND eliminated = 0
                LIMIT 1
            """), {"lyid": league_year_id}).scalar()
            return {"status": "complete", "champion": int(champion) if champion else None}

        return {"error": "No actionable transitions — rounds may still be in progress"}

    return {"series_created": created_all, "rounds_advanced": list({c["round"] for c in created_all})}


# =====================================================================
# Bracket Query
# =====================================================================

def get_bracket(conn, league_year_id: int, league_level: int) -> Dict[str, Any]:
    """Return full bracket state for the frontend."""
    series = conn.execute(sa_text("""
        SELECT ps.*, ta.team_abbrev AS abbrev_a, tb.team_abbrev AS abbrev_b,
               tw.team_abbrev AS winner_abbrev
        FROM playoff_series ps
        JOIN teams ta ON ta.id = ps.team_a_id
        JOIN teams tb ON tb.id = ps.team_b_id
        LEFT JOIN teams tw ON tw.id = ps.winner_team_id
        WHERE ps.league_year_id = :lyid AND ps.league_level = :level
        ORDER BY FIELD(ps.round, 'WC','DS','CS','WS','QF','SF','F',
                       'CWS_W1','CWS_W2','CWS_W3',
                       'CWS_L1','CWS_L2','CWS_L3','CWS_L4',
                       'CWS_F1','CWS_F2'),
                 ps.conference, ps.series_number
    """), {"lyid": league_year_id, "level": league_level}).mappings().all()

    result = {"league_year_id": league_year_id, "league_level": league_level, "rounds": {}}

    for s in series:
        rnd = s["round"]
        result["rounds"].setdefault(rnd, []).append({
            "series_id": int(s["id"]),
            "conference": s["conference"],
            "team_a": {"id": int(s["team_a_id"]), "abbrev": s["abbrev_a"], "seed": int(s["seed_a"]) if s["seed_a"] else None},
            "team_b": {"id": int(s["team_b_id"]), "abbrev": s["abbrev_b"], "seed": int(s["seed_b"]) if s["seed_b"] else None},
            "wins_a": int(s["wins_a"]),
            "wins_b": int(s["wins_b"]),
            "series_length": int(s["series_length"]),
            "status": s["status"],
            "winner": {"id": int(s["winner_team_id"]), "abbrev": s["winner_abbrev"]} if s["winner_team_id"] else None,
        })

    # Add CWS bracket state if level 3
    if league_level == 3:
        cws = conn.execute(sa_text("""
            SELECT cb.*, t.team_abbrev
            FROM cws_bracket cb
            JOIN teams t ON t.id = cb.team_id
            WHERE cb.league_year_id = :lyid
            ORDER BY cb.seed
        """), {"lyid": league_year_id}).mappings().all()

        result["cws_bracket"] = [{
            "team_id": int(c["team_id"]),
            "team_abbrev": c["team_abbrev"],
            "seed": int(c["seed"]),
            "qualification": c["qualification"],
            "losses": int(c["losses"]),
            "eliminated": bool(c["eliminated"]),
            "bracket_side": c["bracket_side"],
        } for c in cws]

    return result


# =====================================================================
# Pending / Catch-up queries
# =====================================================================

def get_pending_playoff_games(
    conn, league_year_id: int, league_level: int,
) -> List[Dict[str, Any]]:
    """
    Return all gamelist rows for pending/active playoff series that do NOT
    yet have a game_results row.  These are the games waiting to be simulated.
    """
    rows = conn.execute(sa_text("""
        SELECT gl.id AS game_id, gl.away_team, gl.home_team,
               gl.season_week, gl.season_subweek,
               ta.team_abbrev AS away_abbrev,
               th.team_abbrev AS home_abbrev,
               ps.id AS series_id, ps.round, ps.series_number,
               ps.wins_a, ps.wins_b, ps.series_length, ps.status AS series_status
        FROM gamelist gl
        JOIN teams ta ON ta.id = gl.away_team
        JOIN teams th ON th.id = gl.home_team
        JOIN playoff_series ps
          ON ps.league_year_id = :lyid AND ps.league_level = :level
          AND ps.status IN ('pending', 'active')
          AND ((ps.team_a_id = gl.home_team AND ps.team_b_id = gl.away_team)
            OR (ps.team_a_id = gl.away_team AND ps.team_b_id = gl.home_team))
        LEFT JOIN game_results gr ON gr.game_id = gl.id
        WHERE gl.game_type = 'playoff'
          AND gl.league_level = :level
          AND gr.game_id IS NULL
        ORDER BY gl.season_week, gl.season_subweek, ps.round, ps.series_number
    """), {"lyid": league_year_id, "level": league_level}).mappings().all()

    return [{
        "game_id": int(r["game_id"]),
        "away_team": int(r["away_team"]),
        "home_team": int(r["home_team"]),
        "away_abbrev": r["away_abbrev"],
        "home_abbrev": r["home_abbrev"],
        "season_week": int(r["season_week"]),
        "season_subweek": r["season_subweek"],
        "series_id": int(r["series_id"]),
        "round": r["round"],
        "series_number": int(r["series_number"]),
        "wins_a": int(r["wins_a"]),
        "wins_b": int(r["wins_b"]),
        "series_length": int(r["series_length"]),
        "series_status": r["series_status"],
    } for r in rows]


def process_completed_playoff_games(
    conn, league_year_id: int, league_level: int,
) -> List[Dict[str, Any]]:
    """
    Find completed playoff game_results that haven't been reflected in
    playoff_series yet (wins not counted) and process them in order.

    This is a catch-up mechanism: it identifies games whose results exist
    but whose series wins_a/wins_b don't yet account for them.
    """
    # Find all completed playoff games for active/pending series
    rows = conn.execute(sa_text("""
        SELECT gr.game_id, gr.winning_team_id, gr.home_team_id, gr.away_team_id,
               gr.season_week, gr.season_subweek
        FROM game_results gr
        JOIN gamelist gl ON gl.id = gr.game_id
        JOIN playoff_series ps
          ON ps.league_year_id = :lyid AND ps.league_level = :level
          AND ps.status IN ('pending', 'active')
          AND ((ps.team_a_id = gr.home_team_id AND ps.team_b_id = gr.away_team_id)
            OR (ps.team_a_id = gr.away_team_id AND ps.team_b_id = gr.home_team_id))
        WHERE gr.game_type = 'playoff'
          AND gl.league_level = :level
        ORDER BY gr.season_week, gr.season_subweek
    """), {"lyid": league_year_id, "level": league_level}).mappings().all()

    # Now check which of these have NOT been counted yet.
    # Strategy: count game_results for each series vs wins_a + wins_b.
    # If more results than counted wins, process the uncounted ones.
    updates = []
    for r in rows:
        game_id = int(r["game_id"])
        result = update_series_after_game(conn, game_id)
        if result:
            updates.append(result)

    return updates


# =====================================================================
# Wipe / Reset
# =====================================================================

def wipe_playoffs(
    conn, league_year_id: int, league_level: int,
) -> Dict[str, Any]:
    """
    Delete all playoff data for a given league year and level so the user
    can regenerate the bracket from scratch.

    Removes:
      - playoff_series rows
      - gamelist rows (game_type='playoff')
      - game_results rows (game_type='playoff')
      - game_batting_lines / game_pitching_lines for those games
      - game_substitutions for those games
      - cws_bracket rows (level 3 only)

    Does NOT touch:
      - Season-accumulated player stats (would require reverse-engineering
        each game's contribution — too fragile).  Playoff stats in season
        totals are left as-is.
      - Stamina / fatigue state.
    """
    params = {"lyid": league_year_id, "level": league_level}

    # 1. Identify the gamelist IDs we need to cascade-delete from
    game_ids_rows = conn.execute(sa_text("""
        SELECT id FROM gamelist
        WHERE game_type = 'playoff' AND league_level = :level
          AND season IN (
              SELECT s.id FROM seasons s
              JOIN league_years ly ON ly.league_year = s.year
              WHERE ly.id = :lyid
          )
    """), params).all()
    game_ids = [int(r[0]) for r in game_ids_rows]

    deleted = {
        "game_ids": len(game_ids),
        "game_results": 0,
        "game_batting_lines": 0,
        "game_pitching_lines": 0,
        "game_substitutions": 0,
        "gamelist": 0,
        "playoff_series": 0,
        "cws_bracket": 0,
    }

    if game_ids:
        # Build a safe comma-separated list for IN clause
        gid_csv = ",".join(str(g) for g in game_ids)

        for table in (
            "game_batting_lines",
            "game_pitching_lines",
            "game_substitutions",
        ):
            res = conn.execute(sa_text(
                f"DELETE FROM {table} WHERE game_id IN ({gid_csv})"
            ))
            deleted[table] = res.rowcount

        # game_results
        res = conn.execute(sa_text(
            f"DELETE FROM game_results WHERE game_id IN ({gid_csv})"
        ))
        deleted["game_results"] = res.rowcount

        # gamelist
        res = conn.execute(sa_text(
            f"DELETE FROM gamelist WHERE id IN ({gid_csv})"
        ))
        deleted["gamelist"] = res.rowcount

    # 2. playoff_series
    res = conn.execute(sa_text("""
        DELETE FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
    """), params)
    deleted["playoff_series"] = res.rowcount

    # 3. cws_bracket (level 3 only)
    if league_level == 3:
        res = conn.execute(sa_text("""
            DELETE FROM cws_bracket WHERE league_year_id = :lyid
        """), {"lyid": league_year_id})
        deleted["cws_bracket"] = res.rowcount

    log.info(
        "playoffs: wiped level %d for league_year %d: %s",
        league_level, league_year_id, deleted,
    )

    return deleted


# =====================================================================
# Helpers
# =====================================================================

def _get_league_year(conn, league_year_id: int) -> int:
    """Get the league_year (calendar year) from league_year_id."""
    row = conn.execute(sa_text(
        "SELECT league_year FROM league_years WHERE id = :lyid"
    ), {"lyid": league_year_id}).first()
    if not row:
        raise ValueError(f"league_year_id {league_year_id} not found")
    return int(row[0])


_SUBWEEKS = ["a", "b", "c", "d"]


def _next_available_subweek(
    conn, league_year_id: int, league_level: int,
    team_a_id: int, team_b_id: int, start_week: int,
) -> Tuple[int, str]:
    """
    Find the next available (week, subweek) slot for a playoff game between
    these two teams, starting from start_week.  Checks gamelist for existing
    entries to avoid collisions.
    """
    # Get all occupied subweeks where EITHER team already has a playoff game
    occupied = conn.execute(sa_text("""
        SELECT season_week, season_subweek
        FROM gamelist
        WHERE game_type = 'playoff' AND league_level = :level
          AND (home_team IN (:ta, :tb) OR away_team IN (:ta, :tb))
          AND season_week >= :sw
        ORDER BY season_week, season_subweek
    """), {
        "level": league_level,
        "ta": team_a_id, "tb": team_b_id,
        "sw": start_week,
    }).all()

    used = {(int(r[0]), str(r[1])) for r in occupied}

    # Find first free slot
    week = start_week
    for _ in range(20):  # safety: don't loop forever
        for sw in _SUBWEEKS:
            if (week, sw) not in used:
                return week, sw
        week += 1

    # Fallback (shouldn't happen)
    return start_week, "a"


def _insert_single_playoff_game(
    conn, league_year_id: int, league_level: int,
    home_team_id: int, away_team_id: int,
    week: int, subweek: str,
) -> None:
    """Insert one playoff game into gamelist with the specified week/subweek."""
    season_id = conn.execute(sa_text("""
        SELECT s.id FROM seasons s
        JOIN league_years ly ON ly.league_year = s.year
        WHERE ly.id = :lyid LIMIT 1
    """), {"lyid": league_year_id}).scalar()

    conn.execute(sa_text("""
        INSERT INTO gamelist
            (away_team, home_team, season_week, season_subweek,
             league_level, season, random_seed, game_type)
        VALUES
            (:away, :home, :week, :sub,
             :level, :season, NULL, 'playoff')
    """), {
        "away": away_team_id, "home": home_team_id,
        "week": week, "sub": subweek,
        "level": league_level, "season": season_id,
    })

    log.info(
        "playoffs: inserted game week %d/%s: %d @ %d (level %d)",
        week, subweek, away_team_id, home_team_id, league_level,
    )


