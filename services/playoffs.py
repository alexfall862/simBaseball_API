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

            # Generate games via schedule_generator.add_series
            from services.schedule_generator import add_series
            add_series(
                engine,
                league_year=_get_league_year(conn, league_year_id),
                league_level=9,
                home_team_id=team_a["team_id"],  # higher seed hosts all Bo3
                away_team_id=team_b["team_id"],
                week=start_week,
                games=3,
                game_type="playoff",
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
    Looks up the series via gamelist → playoff_series matching.

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

    clinch_target = CLINCH[series_len]
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

    return {
        "series_id": series_id,
        "wins_a": wins_a,
        "wins_b": wins_b,
        "status": status,
        "winner_team_id": winner_id,
    }


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
    else:
        return _advance_milb_round(conn, engine, league_year_id, league_level, complete_rounds)


def _advance_mlb_round(
    conn, engine, league_year_id: int, complete_rounds: Dict
) -> Dict[str, Any]:
    """Advance MLB playoffs to the next round."""

    # Determine which round just completed
    for rnd in MLB_ROUNDS:
        info = complete_rounds.get(rnd)
        if info and info["total"] == info["done"]:
            next_idx = MLB_ROUNDS.index(rnd) + 1
            if next_idx >= len(MLB_ROUNDS):
                return {"status": "complete", "message": "World Series is complete!"}
            next_round = MLB_ROUNDS[next_idx]
            break
    else:
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
    league_year = _get_league_year(conn, league_year_id)

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

                # Bo5 games: 2-2-1 home pattern
                _generate_series_games(
                    engine, league_year, 9,
                    top_seed["team_id"], opp_tid,
                    next_week, 4, HOME_PATTERNS[5],
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

            _generate_series_games(
                engine, league_year, 9,
                int(w1["winner_team_id"]), int(w2["winner_team_id"]),
                next_week, 4, HOME_PATTERNS[7],
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

        _generate_series_games(
            engine, league_year, 9,
            team_a_id, team_b_id,
            next_week, 4, HOME_PATTERNS[7],
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
    league_year = _get_league_year(conn, league_year_id)
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

        _generate_series_games(
            engine, league_year, league_level,
            team_a["team_id"], team_b["team_id"],
            start_week, 4, HOME_PATTERNS[7],
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
    league_year = _get_league_year(conn, league_year_id)

    for rnd in MILB_ROUNDS:
        info = complete_rounds.get(rnd)
        if info and info["total"] == info["done"]:
            next_idx = MILB_ROUNDS.index(rnd) + 1
            if next_idx >= len(MILB_ROUNDS):
                return {"status": "complete", "message": "Finals complete!"}
            next_round = MILB_ROUNDS[next_idx]
            break
    else:
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

            _generate_series_games(
                engine, league_year, league_level,
                int(w_a["winner_team_id"]), int(w_b["winner_team_id"]),
                next_week, 4, HOME_PATTERNS[7],
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

        _generate_series_games(
            engine, league_year, league_level,
            int(w_a["winner_team_id"]), int(w_b["winner_team_id"]),
            next_week, 4, HOME_PATTERNS[7],
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
    engine = get_engine()
    league_year = _get_league_year(conn, league_year_id)

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

        # Single game — higher seed hosts
        from services.schedule_generator import add_series
        add_series(
            engine,
            league_year=league_year,
            league_level=3,
            home_team_id=team_a["team_id"],
            away_team_id=team_b["team_id"],
            week=start_week,
            games=1,
            game_type="playoff",
        )

        created.append({
            "round": "CWS_W1",
            "matchup": f"{team_a['team_abbrev']} (#{seed_a}) vs {team_b['team_abbrev']} (#{seed_b})",
        })

    return {"series_created": created, "bracket_size": len(field)}


def advance_cws_round(conn, league_year_id: int) -> Dict[str, Any]:
    """
    Advance the CWS bracket. After each round:
    - Winners stay in winners bracket
    - Losers drop to losers bracket (or get eliminated if already there)
    - When 2 teams remain, play championship (if loser bracket team wins,
      they play again since the winners bracket team hasn't lost yet).
    """
    engine = get_engine()
    league_year = _get_league_year(conn, league_year_id)

    # Get all CWS series for this league year
    all_series = conn.execute(sa_text("""
        SELECT id, round, series_number, team_a_id, team_b_id,
               winner_team_id, status
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
          AND round LIKE 'CWS_%'
        ORDER BY round, series_number
    """), {"lyid": league_year_id}).mappings().all()

    # Get bracket state
    bracket = conn.execute(sa_text("""
        SELECT team_id, seed, losses, eliminated, bracket_side
        FROM cws_bracket
        WHERE league_year_id = :lyid AND eliminated = 0
        ORDER BY seed
    """), {"lyid": league_year_id}).mappings().all()

    # Find the latest complete round
    rounds_by_name: Dict[str, List] = {}
    for s in all_series:
        rounds_by_name.setdefault(s["round"], []).append(s)

    latest_complete = None
    for rnd_name in sorted(rounds_by_name.keys()):
        rnd_series = rounds_by_name[rnd_name]
        if all(s["status"] == "complete" for s in rnd_series):
            latest_complete = rnd_name

    if not latest_complete:
        return {"error": "No complete CWS round found"}

    # Process results: update bracket losses
    for s in rounds_by_name[latest_complete]:
        if s["status"] != "complete":
            continue
        winner_id = int(s["winner_team_id"])
        loser_id = int(s["team_a_id"]) if winner_id != int(s["team_a_id"]) else int(s["team_b_id"])

        # Increment loser's losses
        conn.execute(sa_text("""
            UPDATE cws_bracket
            SET losses = losses + 1,
                bracket_side = CASE WHEN losses + 1 >= 2 THEN 'eliminated' ELSE 'losers' END,
                eliminated = CASE WHEN losses + 1 >= 2 THEN 1 ELSE 0 END
            WHERE league_year_id = :lyid AND team_id = :tid
        """), {"lyid": league_year_id, "tid": loser_id})

    # Refresh bracket state after updates
    bracket = conn.execute(sa_text("""
        SELECT team_id, seed, losses, eliminated, bracket_side
        FROM cws_bracket
        WHERE league_year_id = :lyid AND eliminated = 0
        ORDER BY seed
    """), {"lyid": league_year_id}).mappings().all()

    remaining = [dict(b) for b in bracket]

    if len(remaining) <= 1:
        winner = remaining[0] if remaining else None
        return {
            "status": "complete",
            "champion": winner["team_id"] if winner else None,
        }

    # Determine next round name
    round_num = int(latest_complete.split("_")[-1].replace("W", "").replace("L", "").replace("F", "99"))
    winners_teams = [t for t in remaining if t["bracket_side"] == "winners"]
    losers_teams = [t for t in remaining if t["bracket_side"] == "losers"]

    # Get the last week used
    last_week_row = conn.execute(sa_text("""
        SELECT MAX(start_week) AS last_week FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
    """), {"lyid": league_year_id}).mappings().first()
    next_week = int(last_week_row["last_week"]) + 1

    created = []

    # Championship: if only 2 teams remain
    if len(remaining) == 2:
        t1, t2 = remaining[0], remaining[1]
        # Higher seed is team_a
        if t1["seed"] > t2["seed"]:
            t1, t2 = t2, t1

        next_round = "CWS_F1"
        conn.execute(sa_text("""
            INSERT INTO playoff_series
                (league_year_id, league_level, round, series_number,
                 team_a_id, team_b_id, seed_a, seed_b,
                 series_length, status, start_week, conference)
            VALUES
                (:lyid, 3, :rnd, 1,
                 :team_a, :team_b, :seed_a, :seed_b,
                 1, 'pending', :week, NULL)
        """), {
            "lyid": league_year_id, "rnd": next_round,
            "team_a": t1["team_id"], "team_b": t2["team_id"],
            "seed_a": t1["seed"], "seed_b": t2["seed"],
            "week": next_week,
        })

        from services.schedule_generator import add_series
        add_series(
            engine, league_year=league_year, league_level=3,
            home_team_id=t1["team_id"], away_team_id=t2["team_id"],
            week=next_week, games=1, game_type="playoff",
        )

        created.append({"round": next_round, "matchup": f"#{t1['seed']} vs #{t2['seed']}"})
        return {"round_advanced": next_round, "series_created": created, "week": next_week}

    # Generate next winners bracket round
    if len(winners_teams) >= 2:
        next_w_round = f"CWS_W{round_num + 1}"
        winners_teams.sort(key=lambda x: x["seed"])
        for i in range(0, len(winners_teams), 2):
            if i + 1 >= len(winners_teams):
                break
            t1 = winners_teams[i]
            t2 = winners_teams[i + 1]
            snum = (i // 2) + 1

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
                "lyid": league_year_id, "rnd": next_w_round, "snum": snum,
                "team_a": t1["team_id"], "team_b": t2["team_id"],
                "seed_a": t1["seed"], "seed_b": t2["seed"],
                "week": next_week,
            })

            from services.schedule_generator import add_series
            add_series(
                engine, league_year=league_year, league_level=3,
                home_team_id=t1["team_id"], away_team_id=t2["team_id"],
                week=next_week, games=1, game_type="playoff",
            )
            created.append({"round": next_w_round, "matchup": f"#{t1['seed']} vs #{t2['seed']}"})

    # Generate next losers bracket round
    if len(losers_teams) >= 2:
        next_l_round = f"CWS_L{round_num + 1}"
        losers_teams.sort(key=lambda x: x["seed"])
        for i in range(0, len(losers_teams), 2):
            if i + 1 >= len(losers_teams):
                break
            t1 = losers_teams[i]
            t2 = losers_teams[i + 1]
            snum = (i // 2) + 1

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
                "lyid": league_year_id, "rnd": next_l_round, "snum": snum,
                "team_a": t1["team_id"], "team_b": t2["team_id"],
                "seed_a": t1["seed"], "seed_b": t2["seed"],
                "week": next_week,
            })

            from services.schedule_generator import add_series
            add_series(
                engine, league_year=league_year, league_level=3,
                home_team_id=t1["team_id"], away_team_id=t2["team_id"],
                week=next_week, games=1, game_type="playoff",
            )
            created.append({"round": next_l_round, "matchup": f"#{t1['seed']} vs #{t2['seed']}"})

    return {"round_advanced": f"W{round_num+1}/L{round_num+1}", "series_created": created, "week": next_week}


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
                       'CWS_W1','CWS_W2','CWS_W3','CWS_L1','CWS_L2','CWS_L3',
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


def _generate_series_games(
    engine, league_year: int, league_level: int,
    home_team_id: int, away_team_id: int,
    start_week: int, games_per_subweek: int,
    home_pattern: List[bool],
) -> None:
    """
    Generate games for a series across subweeks.
    Uses add_series() which handles up to 4 games per week (subweeks a-d).
    For series longer than 4 games, spills into next week.
    """
    from services.schedule_generator import add_series

    total_games = len(home_pattern)
    week = start_week
    game_idx = 0

    while game_idx < total_games:
        batch = min(4, total_games - game_idx)
        batch_pattern = home_pattern[game_idx:game_idx + batch]

        # Check if all games in this batch have the same home team
        # If mixed, we need individual game insertions
        all_home = all(p for p in batch_pattern)
        all_away = all(not p for p in batch_pattern)

        if all_home:
            add_series(
                engine, league_year=league_year, league_level=league_level,
                home_team_id=home_team_id, away_team_id=away_team_id,
                week=week, games=batch, game_type="playoff",
            )
        elif all_away:
            add_series(
                engine, league_year=league_year, league_level=league_level,
                home_team_id=away_team_id, away_team_id=home_team_id,
                week=week, games=batch, game_type="playoff",
            )
        else:
            # Mixed home/away — insert games one at a time
            for p in batch_pattern:
                if p:
                    add_series(
                        engine, league_year=league_year, league_level=league_level,
                        home_team_id=home_team_id, away_team_id=away_team_id,
                        week=week, games=1, game_type="playoff",
                    )
                else:
                    add_series(
                        engine, league_year=league_year, league_level=league_level,
                        home_team_id=away_team_id, away_team_id=home_team_id,
                        week=week, games=1, game_type="playoff",
                    )

        game_idx += batch
        week += 1
