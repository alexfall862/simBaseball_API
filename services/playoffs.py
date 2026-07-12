# services/playoffs.py
"""
Playoff bracket generation, series tracking, and round advancement for:
  - MLB (level 9): 12-team bracket (3 div winners + 3 WC per league)
  - Minor Leagues (levels 5-8): Top 8 by record, single-elimination Bo7
  - College Conference Tournaments (level 3): Single-elimination per conference, with byes
  - College World Series (level 3): Conference tourney winners + at-large, double-elimination
"""

import logging
import math
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
# NCAA 64-team college postseason (level 3)
#
# Four stages, matching real NCAA Division I baseball:
#   Regionals       – 16 regionals x 4 teams, double-elimination (Bo1 games)
#   Super Regionals – 16 regional winners -> 8 best-of-3 series
#   MCWS (Omaha)    – 8 winners -> two 4-team double-elimination brackets
#   MCWS Finals     – 2 bracket winners -> best-of-3 for the title
#
# Regionals and MCWS brackets are the SAME 4-team double-elimination format, so
# both run through one engine (_de_advance_group).  Group membership is keyed by
# the playoff_series ``conference`` column:
#     Regionals       -> 'R01'..'R16'
#     Super Regionals -> 'SR1'..'SR8'   (round 'SUP')
#     MCWS brackets   -> 'MCWS_A' / 'MCWS_B'
#     Finals          -> conference NULL, round 'FINAL'
# ---------------------------------------------------------------------------

# Round suffixes inside one 4-team double-elim group.  Full round name is
# f"{prefix}_{suffix}" with prefix 'REG' (regional) or 'MCWS' (Omaha bracket):
#   G1  – two opening games (#1 v #4, #2 v #3)
#   WF  – winners' final (the two G1 winners)
#   LB  – losers' bracket (the two G1 losers; elimination game)
#   L2  – losers' final (WF loser vs LB winner; elimination game)
#   RF  – regional/bracket final (undefeated WF winner vs L2 winner)
#   RF2 – if-necessary decider (only if the losers-bracket team wins RF)
DE_SUFFIXES = ["G1", "WF", "LB", "L2", "RF", "RF2"]

# MCWS: which super-regional anchors (= the higher national seed of each super
# regional, SR_k anchored by regional k) land in each Omaha bracket.  This is the
# standard 8-team S-curve split that keeps national seeds 1 and 2 apart until the
# finals.  Within a bracket the four teams are seeded 1..4 by ascending anchor.
MCWS_BRACKET_ANCHORS = {"MCWS_A": [1, 4, 5, 8], "MCWS_B": [2, 3, 6, 7]}

NCAA_FIELD_SIZE = 64
NCAA_NUM_REGIONALS = 16
NCAA_NATIONAL_SEEDS = 16

# ---------------------------------------------------------------------------
# Conference Tournament bracket (single elimination, Bo1, byes for top seeds)
# ---------------------------------------------------------------------------
CT_ROUND_PREFIX = "CT_R"


def _ct_bracket_info(num_teams: int) -> Dict[str, int]:
    """
    Compute bracket parameters for a conference tournament of *num_teams*.

    Returns dict with:
      field_size    – number of teams in the bracket (== num_teams)
      total_rounds  – ceil(log2(N))
      play_in_games – first-round games when N is not a power of 2 (else 0)
      num_byes      – top seeds that skip the first round (else 0)
    """
    if num_teams < 2:
        return {"field_size": 0, "total_rounds": 0, "play_in_games": 0, "num_byes": 0}
    is_power_of_2 = (num_teams & (num_teams - 1)) == 0
    if is_power_of_2:
        return {
            "field_size": num_teams,
            "total_rounds": int(math.log2(num_teams)),
            "play_in_games": 0,
            "num_byes": 0,
        }
    total_rounds = math.ceil(math.log2(num_teams))
    p = 1 << (total_rounds - 1)            # largest power of 2 < num_teams
    play_in_games = num_teams - p
    num_byes = 2 * p - num_teams
    return {
        "field_size": num_teams,
        "total_rounds": total_rounds,
        "play_in_games": play_in_games,
        "num_byes": num_byes,
    }


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

    team_a_id = int(series["team_a_id"])
    team_b_id = int(series["team_b_id"])
    start_week = int(series["start_week"])
    league_year_id = int(series["league_year_id"])
    league_level = int(series["league_level"])

    # Idempotency guard: this may be called more than once for the same series
    # state (the recount-based update runs per game).  If an unplayed game for
    # this pair already exists in the series' week window, don't create another.
    next_row = conn.execute(sa_text("""
        SELECT MIN(start_week) AS ns FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
          AND start_week > :sw
          AND ((team_a_id = :a AND team_b_id = :b)
            OR (team_a_id = :b AND team_b_id = :a))
    """), {"lyid": league_year_id, "level": league_level, "sw": start_week,
           "a": team_a_id, "b": team_b_id}).mappings().first()
    next_start = int(next_row["ns"]) if next_row and next_row["ns"] is not None else 10 ** 9
    unplayed = conn.execute(sa_text("""
        SELECT COUNT(*) FROM gamelist gl
        LEFT JOIN game_results gr ON gr.game_id = gl.id
        WHERE gl.game_type = 'playoff' AND gl.league_level = :level
          AND gl.season_week >= :sw AND gl.season_week < :next
          AND gr.game_id IS NULL
          AND ((gl.home_team = :a AND gl.away_team = :b)
            OR (gl.home_team = :b AND gl.away_team = :a))
          AND gl.season = (
              SELECT s.id FROM seasons s
              JOIN league_years ly ON ly.league_year = s.year
              WHERE ly.id = :lyid LIMIT 1)
    """), {"level": league_level, "sw": start_week, "next": next_start,
           "a": team_a_id, "b": team_b_id, "lyid": league_year_id}).scalar()
    if int(unplayed or 0) > 0:
        return None

    # Determine home/away from the pattern
    pattern = HOME_PATTERNS[series_len]

    if pattern[game_idx]:
        home, away = team_a_id, team_b_id
    else:
        home, away = team_b_id, team_a_id

    # Determine week and subweek: each game in the series goes on the next
    # available subweek slot (a→b→c→d, then spill to next week).
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
# Seed persistence (manual-override support)
# =====================================================================

def _table_exists(conn, table: str) -> bool:
    """
    True if *table* exists in the current schema.  Used to guard optional
    tables (e.g. ``playoff_seeds``) so a database that predates a migration
    doesn't crash the whole transaction with a 1146 "table doesn't exist"
    error — issuing a failing statement inside ``engine.begin()`` would abort
    every other write in the same call.
    """
    return bool(conn.execute(sa_text("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = :t
        LIMIT 1
    """), {"t": table}).first())


def _persist_seeds(
    conn, league_year_id: int, league_level: int, field: Any,
) -> None:
    """
    Persist a seeded field to ``playoff_seeds`` so later rounds honor manual
    seeding overrides instead of re-deriving from records.

    ``field`` may be a dict ``{conference: [team, ...]}`` (MLB) or a flat list
    (other formats).  Each team needs ``team_id`` and ``seed``; ``conference``
    and ``qualifier`` are optional.  Existing rows for this (year, level) are
    cleared first so the call is safe to repeat.

    No-op if the ``playoff_seeds`` table is absent (pre-migration DB); the
    consumers all fall back to record-based seeding.
    """
    if not _table_exists(conn, "playoff_seeds"):
        return

    conn.execute(sa_text("""
        DELETE FROM playoff_seeds
        WHERE league_year_id = :lyid AND league_level = :level
    """), {"lyid": league_year_id, "level": league_level})

    groups = field.items() if isinstance(field, dict) else [("", field)]
    for conf, teams in groups:
        for t in teams:
            conn.execute(sa_text("""
                INSERT INTO playoff_seeds
                    (league_year_id, league_level, conference, seed, team_id, qualifier)
                VALUES (:lyid, :level, :conf, :seed, :tid, :qual)
            """), {
                "lyid": league_year_id, "level": league_level,
                "conf": conf or (t.get("conference") or ""),
                "seed": int(t["seed"]), "tid": int(t["team_id"]),
                "qual": t.get("qualifier"),
            })


def _get_persisted_seeds(
    conn, league_year_id: int, league_level: int, conference: str = "",
) -> Dict[int, Dict[str, Any]]:
    """
    Return ``{seed: {team_id, seed, team_abbrev}}`` for a persisted field, or an
    empty dict if none was stored (pre-migration brackets fall back to records).
    """
    if not _table_exists(conn, "playoff_seeds"):
        return {}

    rows = conn.execute(sa_text("""
        SELECT ps.seed, ps.team_id, t.team_abbrev
        FROM playoff_seeds ps
        JOIN teams t ON t.id = ps.team_id
        WHERE ps.league_year_id = :lyid AND ps.league_level = :level
          AND ps.conference = :conf
        ORDER BY ps.seed
    """), {"lyid": league_year_id, "level": league_level, "conf": conference}).mappings().all()

    return {
        int(r["seed"]): {
            "team_id": int(r["team_id"]),
            "seed": int(r["seed"]),
            "team_abbrev": r["team_abbrev"],
        }
        for r in rows
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
    existing = conn.execute(sa_text("""
        SELECT COUNT(*) FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 9
    """), {"lyid": league_year_id}).scalar()
    if existing:
        raise ValueError(
            "MLB bracket already exists for this league year — "
            "wipe playoffs (MLB) before regenerating."
        )

    # Persist the (possibly hand-edited) seeding so the DS round reads the bye
    # teams from here instead of re-deriving seeds 1 & 2 from records.
    _persist_seeds(conn, league_year_id, 9, field)

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

    Games have no FK to a series, so a game is matched to the series with the
    same team pair whose ``start_week`` is the greatest at/before the game's
    week.  This matters for double-elimination rematches (the winners' final and
    the regional final can be the SAME pair): matching on the pair alone would
    re-apply a stale earlier-round result to the later series.  Win counts are
    RECOUNTED from every result inside that series' week window, so the call is
    idempotent (safe to run repeatedly, e.g. from the catch-up scanner).
    """
    # Get game info from game_results + gamelist for scoping
    game_row = conn.execute(sa_text("""
        SELECT gr.game_id, gr.home_team_id, gr.away_team_id,
               gr.winning_team_id, gr.game_type, gr.season_week,
               gl.league_level,
               ly.id AS league_year_id
        FROM game_results gr
        JOIN gamelist gl ON gl.id = gr.game_id
        JOIN seasons s ON s.id = gl.season
        JOIN league_years ly ON ly.league_year = s.year
        WHERE gr.game_id = :gid
    """), {"gid": game_id}).mappings().first()

    if not game_row or game_row["game_type"] != "playoff":
        return None

    lyid = int(game_row["league_year_id"])
    level = int(game_row["league_level"])
    home = int(game_row["home_team_id"])
    away = int(game_row["away_team_id"])
    gweek = int(game_row["season_week"])

    # Candidate series for this team pair, in schedule order.
    cands = conn.execute(sa_text("""
        SELECT id, team_a_id, team_b_id, series_length, start_week, status
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
          AND ((team_a_id = :home AND team_b_id = :away)
            OR (team_a_id = :away AND team_b_id = :home))
        ORDER BY start_week
    """), {"lyid": lyid, "level": level, "home": home, "away": away}).mappings().all()

    if not cands:
        log.warning("playoffs: no series found for game %d", game_id)
        return None

    # Owning series = latest one that started at/before this game's week.
    owning = None
    for c in cands:
        if int(c["start_week"]) <= gweek:
            owning = c
    if owning is None:
        owning = cands[0]

    series_id = int(owning["id"])
    team_a_id = int(owning["team_a_id"])
    team_b_id = int(owning["team_b_id"])
    series_len = int(owning["series_length"])
    start_week = int(owning["start_week"])
    later_starts = [int(c["start_week"]) for c in cands if int(c["start_week"]) > start_week]
    next_start = min(later_starts) if later_starts else 10 ** 9

    # Recount wins from every played game in this series' week window.
    tally = conn.execute(sa_text("""
        SELECT gr.winning_team_id AS wid, COUNT(*) AS n
        FROM gamelist gl
        JOIN game_results gr ON gr.game_id = gl.id
        WHERE gl.game_type = 'playoff' AND gl.league_level = :level
          AND gl.season_week >= :start AND gl.season_week < :next
          AND ((gl.home_team = :a AND gl.away_team = :b)
            OR (gl.home_team = :b AND gl.away_team = :a))
          AND gl.season = (
              SELECT s.id FROM seasons s
              JOIN league_years ly ON ly.league_year = s.year
              WHERE ly.id = :lyid LIMIT 1)
        GROUP BY gr.winning_team_id
    """), {"level": level, "start": start_week, "next": next_start,
           "a": team_a_id, "b": team_b_id, "lyid": lyid}).mappings().all()

    wins_a = wins_b = 0
    for r in tally:
        if r["wid"] is None:
            continue
        if int(r["wid"]) == team_a_id:
            wins_a = int(r["n"])
        elif int(r["wid"]) == team_b_id:
            wins_b = int(r["n"])

    clinch_target = CLINCH.get(series_len, 1)
    winner_id = None
    status = "active"

    if wins_a >= clinch_target:
        winner_id = team_a_id
        status = "complete"
    elif wins_b >= clinch_target:
        winner_id = team_b_id
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

            # Get bye teams (seeds 1 and 2) — they're in the field but NOT in
            # any WC series.  Read them from the persisted seeding so manual
            # overrides are honored; fall back to records for pre-migration
            # brackets that never persisted a field.
            conf_field = _get_persisted_seeds(conn, league_year_id, 9, conf)
            if not conf_field:
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
    existing = conn.execute(sa_text("""
        SELECT COUNT(*) FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = :level
    """), {"lyid": league_year_id, "level": league_level}).scalar()
    if existing:
        raise ValueError(
            "Playoff bracket already exists for this level — wipe it before regenerating."
        )

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
# College Conference Tournaments (Level 3) — Single Elimination
# =====================================================================

def determine_conf_tournament_fields(
    conn, league_year_id: int,
) -> Dict[str, List[Dict]]:
    """
    Build the seeded field for every conference tournament.

    Returns ``{conference_name: [team_dict, ...]}`` where each list is sorted
    by conference-record seed (1 = best).  Conferences with < 2 teams and
    "Independent" are excluded.
    """
    by_conf = _get_college_team_records(conn, league_year_id)

    fields: Dict[str, List[Dict]] = {}
    for conf, teams in by_conf.items():
        if conf == "Independent" or len(teams) < 2:
            continue
        # Sort: conference win%, overall win% tiebreaker, conf wins tiebreaker
        teams.sort(
            key=lambda t: (t["conf_win_pct"], t["win_pct"], t["conf_wins"]),
            reverse=True,
        )
        for i, t in enumerate(teams):
            t["seed"] = i + 1
        fields[conf] = teams

    return fields


def create_conf_tournaments(
    conn, league_year_id: int, start_week: int = 25,
    fields: Optional[Dict[str, List[Dict]]] = None,
) -> Dict[str, Any]:
    """
    Create all conference tournament brackets in one call.

    For each conference:
      - All teams qualify (maximise field).
      - Bracket math determines byes (top seeds skip play-in round).
      - Single-elimination Bo1 games.

    ``fields`` may be supplied to override the computed seeding (admin editor);
    when omitted the field is derived from conference records.
    """
    existing = conn.execute(sa_text("""
        SELECT COUNT(*) FROM conf_tournament_field WHERE league_year_id = :lyid
    """), {"lyid": league_year_id}).scalar()
    if existing:
        raise ValueError(
            "Conference tournaments already exist for this league year — "
            "wipe them before regenerating."
        )

    if fields is None:
        fields = determine_conf_tournament_fields(conn, league_year_id)
    summary: List[Dict] = []
    total_series = 0

    for conf, teams in fields.items():
        info = _ct_bracket_info(len(teams))
        if info["total_rounds"] == 0:
            continue

        num_byes = info["num_byes"]

        # Populate conf_tournament_field table
        for t in teams:
            conn.execute(sa_text("""
                INSERT INTO conf_tournament_field
                    (league_year_id, conference, team_id, seed, has_bye)
                VALUES (:lyid, :conf, :tid, :seed, :bye)
            """), {
                "lyid": league_year_id, "conf": conf,
                "tid": t["team_id"], "seed": t["seed"],
                "bye": 1 if t["seed"] <= num_byes else 0,
            })

        # Build first-round matchups
        if num_byes > 0:
            # Play-in: bottom 2*play_in_games seeds play
            playing = [t for t in teams if t["seed"] > num_byes]
        else:
            # Full first round: all teams play
            playing = list(teams)

        # Pair best-vs-worst within the playing set
        playing.sort(key=lambda t: t["seed"])
        pairs: List[Tuple[Dict, Dict]] = []
        lo, hi = 0, len(playing) - 1
        while lo < hi:
            pairs.append((playing[lo], playing[hi]))
            lo += 1
            hi -= 1

        created_conf: List[Dict] = []
        for snum, (t_a, t_b) in enumerate(pairs, start=1):
            conn.execute(sa_text("""
                INSERT INTO playoff_series
                    (league_year_id, league_level, round, series_number,
                     team_a_id, team_b_id, seed_a, seed_b,
                     series_length, status, start_week, conference)
                VALUES
                    (:lyid, 3, 'CT_R1', :snum,
                     :team_a, :team_b, :seed_a, :seed_b,
                     1, 'pending', :week, :conf)
            """), {
                "lyid": league_year_id, "snum": snum,
                "team_a": t_a["team_id"], "team_b": t_b["team_id"],
                "seed_a": t_a["seed"], "seed_b": t_b["seed"],
                "week": start_week, "conf": conf,
            })

            week, subweek = _next_available_subweek(
                conn, league_year_id, 3,
                t_a["team_id"], t_b["team_id"], start_week,
            )
            _insert_single_playoff_game(
                conn, league_year_id, 3,
                t_a["team_id"], t_b["team_id"], week, subweek,
            )

            created_conf.append({
                "matchup": f"{t_a['team_abbrev']} (#{t_a['seed']}) vs "
                           f"{t_b['team_abbrev']} (#{t_b['seed']})",
            })

        total_series += len(created_conf)
        summary.append({
            "conference": conf,
            "field_size": info["field_size"],
            "total_rounds": info["total_rounds"],
            "num_byes": num_byes,
            "r1_series": len(created_conf),
            "matchups": created_conf,
        })

        log.info(
            "conf tournament: %s — %d teams, %d rounds, %d byes, %d R1 games",
            conf, info["field_size"], info["total_rounds"], num_byes,
            len(created_conf),
        )

    return {"conferences": summary, "total_series": total_series}


def advance_conf_tournaments(
    conn, league_year_id: int, start_week: int = 25,
) -> Dict[str, Any]:
    """
    Advance all conference tournaments that have completed their current round.

    Iterates every conference, finds the latest complete round whose successor
    doesn't yet exist, and creates the next round's matchups.  Handles bye
    merging for the R1→R2 transition when R1 was a play-in round.

    Idempotent: safe to call repeatedly.
    """
    # Load all CT series grouped by (conference, round)
    all_ct = conn.execute(sa_text("""
        SELECT conference, round, status
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
          AND round LIKE 'CT_R%%'
    """), {"lyid": league_year_id}).mappings().all()

    if not all_ct:
        return {"error": "No conference tournament series found"}

    # Build {conference: {round: {total, complete}}}
    conf_rounds: Dict[str, Dict[str, Dict[str, int]]] = {}
    for s in all_ct:
        conf = s["conference"]
        rnd = s["round"]
        conf_rounds.setdefault(conf, {})
        conf_rounds[conf].setdefault(rnd, {"total": 0, "complete": 0})
        conf_rounds[conf][rnd]["total"] += 1
        if s["status"] == "complete":
            conf_rounds[conf][rnd]["complete"] += 1

    advanced: List[Dict] = []
    completed: List[Dict] = []
    no_action: List[str] = []

    for conf, rounds in conf_rounds.items():
        # Get total_rounds for this conference from the field table
        field_count = conn.execute(sa_text("""
            SELECT COUNT(*) FROM conf_tournament_field
            WHERE league_year_id = :lyid AND conference = :conf
        """), {"lyid": league_year_id, "conf": conf}).scalar()

        info = _ct_bracket_info(field_count)
        total_rounds = info["total_rounds"]

        # Find the latest completed round whose next round doesn't exist
        latest_complete_num = None
        for rnd_name, counts in sorted(rounds.items()):
            if counts["total"] != counts["complete"]:
                continue
            rnd_num = int(rnd_name.replace(CT_ROUND_PREFIX, ""))
            next_rnd = f"{CT_ROUND_PREFIX}{rnd_num + 1}"
            if next_rnd not in rounds and rnd_num < total_rounds:
                latest_complete_num = rnd_num

        if latest_complete_num is None:
            # Check if the final round is complete
            final_rnd = f"{CT_ROUND_PREFIX}{total_rounds}"
            if final_rnd in rounds and rounds[final_rnd]["total"] == rounds[final_rnd]["complete"]:
                winner_row = conn.execute(sa_text("""
                    SELECT winner_team_id FROM playoff_series
                    WHERE league_year_id = :lyid AND league_level = 3
                      AND round = :rnd AND conference = :conf AND status = 'complete'
                """), {"lyid": league_year_id, "rnd": final_rnd, "conf": conf}).first()
                if winner_row:
                    completed.append({"conference": conf, "champion": int(winner_row[0])})
            else:
                no_action.append(f"{conf}: rounds still in progress")
            continue

        current_rnd = f"{CT_ROUND_PREFIX}{latest_complete_num}"
        next_rnd_num = latest_complete_num + 1
        next_rnd = f"{CT_ROUND_PREFIX}{next_rnd_num}"

        # Get winners from the completed round
        winners_rows = conn.execute(sa_text("""
            SELECT winner_team_id, seed_a, seed_b, team_a_id
            FROM playoff_series
            WHERE league_year_id = :lyid AND league_level = 3
              AND round = :rnd AND conference = :conf AND status = 'complete'
            ORDER BY series_number
        """), {"lyid": league_year_id, "rnd": current_rnd, "conf": conf}).mappings().all()

        winners = []
        for w in winners_rows:
            wtid = int(w["winner_team_id"])
            seed = min(int(w["seed_a"]), int(w["seed_b"]))
            winners.append({"team_id": wtid, "seed": seed})

        # For R1→R2: merge bye teams if R1 was a play-in round
        if latest_complete_num == 1 and info["num_byes"] > 0:
            bye_rows = conn.execute(sa_text("""
                SELECT team_id, seed FROM conf_tournament_field
                WHERE league_year_id = :lyid AND conference = :conf AND has_bye = 1
            """), {"lyid": league_year_id, "conf": conf}).mappings().all()
            for b in bye_rows:
                winners.append({"team_id": int(b["team_id"]), "seed": int(b["seed"])})

        # Pair best-vs-worst
        winners.sort(key=lambda t: t["seed"])
        pairs: List[Tuple[Dict, Dict]] = []
        lo, hi = 0, len(winners) - 1
        while lo < hi:
            pairs.append((winners[lo], winners[hi]))
            lo += 1
            hi -= 1

        # Determine start_week for next round
        last_week_row = conn.execute(sa_text("""
            SELECT MAX(start_week) AS mw FROM playoff_series
            WHERE league_year_id = :lyid AND league_level = 3
              AND round = :rnd AND conference = :conf
        """), {"lyid": league_year_id, "rnd": current_rnd, "conf": conf}).mappings().first()
        next_week = int(last_week_row["mw"]) + 1 if last_week_row and last_week_row["mw"] else start_week

        created_round: List[Dict] = []
        for snum, (t_a, t_b) in enumerate(pairs, start=1):
            conn.execute(sa_text("""
                INSERT INTO playoff_series
                    (league_year_id, league_level, round, series_number,
                     team_a_id, team_b_id, seed_a, seed_b,
                     series_length, status, start_week, conference)
                VALUES
                    (:lyid, 3, :rnd, :snum,
                     :team_a, :team_b, :seed_a, :seed_b,
                     1, 'pending', :week, :conf)
            """), {
                "lyid": league_year_id, "rnd": next_rnd, "snum": snum,
                "team_a": t_a["team_id"], "team_b": t_b["team_id"],
                "seed_a": t_a["seed"], "seed_b": t_b["seed"],
                "week": next_week, "conf": conf,
            })

            week, subweek = _next_available_subweek(
                conn, league_year_id, 3,
                t_a["team_id"], t_b["team_id"], next_week,
            )
            _insert_single_playoff_game(
                conn, league_year_id, 3,
                t_a["team_id"], t_b["team_id"], week, subweek,
            )

            created_round.append({
                "matchup": f"#{t_a['seed']} vs #{t_b['seed']}",
            })

        advanced.append({
            "conference": conf,
            "round": next_rnd,
            "series_created": len(created_round),
        })

        log.info(
            "conf tournament advance: %s — created %d series for %s",
            conf, len(created_round), next_rnd,
        )

    return {"advanced": advanced, "completed": completed, "no_action": no_action}


def get_conf_tournament_winners(
    conn, league_year_id: int,
) -> Dict[str, int]:
    """
    Return ``{conference_name: winner_team_id}`` only for conferences whose
    tournament has actually finished.

    A conference's true final round is ``CT_R{total_rounds}`` where
    ``total_rounds`` comes from the bracket math for its field size — NOT the
    highest round that currently exists.  Keying off ``MAX(round)`` would treat
    a completed *intermediate* round (e.g. a semifinal, still with multiple
    series) as the final and return several "champions" per conference, only
    one of which survives the dict collapse.  This guard prevents premature /
    wrong CWS auto-bids when the field is built before tournaments complete.
    """
    # Expected final round per conference, derived from field size.
    field_rows = conn.execute(sa_text("""
        SELECT conference, COUNT(*) AS n
        FROM conf_tournament_field
        WHERE league_year_id = :lyid
        GROUP BY conference
    """), {"lyid": league_year_id}).mappings().all()

    final_round: Dict[str, str] = {}
    for r in field_rows:
        info = _ct_bracket_info(int(r["n"]))
        if info["total_rounds"] > 0:
            final_round[r["conference"]] = f"{CT_ROUND_PREFIX}{info['total_rounds']}"

    if not final_round:
        return {}

    rows = conn.execute(sa_text("""
        SELECT conference, round, winner_team_id
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
          AND round LIKE 'CT_R%%' AND status = 'complete'
          AND winner_team_id IS NOT NULL
    """), {"lyid": league_year_id}).mappings().all()

    winners: Dict[str, int] = {}
    for r in rows:
        conf = r["conference"]
        if final_round.get(conf) == r["round"]:
            winners[conf] = int(r["winner_team_id"])
    return winners


def wipe_conf_tournaments(
    conn, league_year_id: int,
) -> Dict[str, Any]:
    """
    Delete all conference tournament data for a league year, leaving CWS
    bracket and other playoff data untouched.
    """
    params = {"lyid": league_year_id}

    # 1. Identify gamelist IDs from CT playoff_series.
    #    Scope strictly to this league year's season and to weeks BEFORE the CWS
    #    begins.  A CT pairing (same conference) can recur as a CWS matchup
    #    (seed pairing), and the same two teams could meet at level 3 in another
    #    season — matching on team pair alone would delete those games too.
    game_ids_rows = conn.execute(sa_text("""
        SELECT gl.id
        FROM gamelist gl
        JOIN playoff_series ps
          ON ps.league_year_id = :lyid AND ps.league_level = 3
          AND ps.round LIKE 'CT_R%%'
          AND ((gl.home_team = ps.team_a_id AND gl.away_team = ps.team_b_id)
            OR (gl.home_team = ps.team_b_id AND gl.away_team = ps.team_a_id))
        WHERE gl.game_type = 'playoff' AND gl.league_level = 3
          AND gl.season IN (
              SELECT s.id FROM seasons s
              JOIN league_years ly ON ly.league_year = s.year
              WHERE ly.id = :lyid
          )
          AND gl.season_week >= ps.start_week
          AND gl.season_week < COALESCE((
              SELECT MIN(start_week) FROM playoff_series
              WHERE league_year_id = :lyid AND league_level = 3
                AND round LIKE 'CWS_%%'
          ), 999999)
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
        "conf_tournament_field": 0,
    }

    if game_ids:
        gid_csv = ",".join(str(g) for g in game_ids)
        for table in ("game_batting_lines", "game_pitching_lines", "game_substitutions"):
            res = conn.execute(sa_text(
                f"DELETE FROM {table} WHERE game_id IN ({gid_csv})"
            ))
            deleted[table] = res.rowcount

        res = conn.execute(sa_text(
            f"DELETE FROM game_results WHERE game_id IN ({gid_csv})"
        ))
        deleted["game_results"] = res.rowcount

        res = conn.execute(sa_text(
            f"DELETE FROM gamelist WHERE id IN ({gid_csv})"
        ))
        deleted["gamelist"] = res.rowcount

    # 2. playoff_series
    res = conn.execute(sa_text("""
        DELETE FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3 AND round LIKE 'CT_R%%'
    """), params)
    deleted["playoff_series"] = res.rowcount

    # 3. conf_tournament_field
    res = conn.execute(sa_text("""
        DELETE FROM conf_tournament_field WHERE league_year_id = :lyid
    """), params)
    deleted["conf_tournament_field"] = res.rowcount

    log.info("conf tournament: wiped for league_year %d: %s", league_year_id, deleted)
    return deleted


# =====================================================================
# College World Series (Level 3) — Double Elimination
# =====================================================================

def _get_college_team_records(
    conn, league_year_id: int,
) -> Dict[str, List[Dict]]:
    """
    Fetch all level-3 teams with overall and conference records, grouped by
    conference name.  Shared by conference tournament seeding and CWS field
    selection.

    Returns ``{conference_name: [team_dict, ...]}`` where each team_dict has:
        team_id, team_abbrev, conference, wins, losses, win_pct,
        conf_wins, conf_losses, conf_win_pct
    """
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

    return by_conf


def determine_cws_field(conn, league_year_id: int) -> List[Dict]:
    """
    Build the 64-team NCAA tournament field for the college (level 3) postseason.

    Selection (mirrors real NCAA):
      * Auto-bids  — one per conference: the conference-tournament champion
        (``get_conf_tournament_winners``), or the best conference record if that
        conference's tournament hasn't finished.
      * At-large   — fill to 64 with the best remaining teams by overall win%.

    Seeding:
      * Overall selection ``seed`` 1..64 by win% (tiebreak conf win%, wins).
      * Top 16 get ``national_seed`` 1..16 and anchor the 16 regionals at
        ``regional_seed`` 1.
      * The remaining 48 are snake-drafted into ``regional_seed`` 2/3/4 so the
        strongest regionals draw the weakest pods (balance).

    Returns a flat list of 64 dicts, each with:
        team_id, team_abbrev, seed, national_seed|None, regional_no (1-16),
        regional_seed (1-4), qualifier, plus the record fields.
    """
    by_conf = _get_college_team_records(conn, league_year_id)
    ct_winners = get_conf_tournament_winners(conn, league_year_id)

    auto_bids: List[Dict] = []
    used: set = set()
    for conf, teams in by_conf.items():
        if conf == "Independent" or not teams:
            continue
        champ = None
        if conf in ct_winners:
            wid = ct_winners[conf]
            champ = next((t for t in teams if t["team_id"] == wid), None)
        if champ is None:
            champ = sorted(
                teams, key=lambda x: (x["conf_win_pct"], x["win_pct"]),
                reverse=True,
            )[0]
        auto_bids.append({**champ, "qualifier": "auto_bid"})
        used.add(champ["team_id"])

    all_teams = [t for teams in by_conf.values() for t in teams]
    at_large_pool = sorted(
        (t for t in all_teams if t["team_id"] not in used),
        key=lambda x: (x["win_pct"], x["conf_win_pct"]), reverse=True,
    )
    needed = NCAA_FIELD_SIZE - len(auto_bids)
    at_large = [{**t, "qualifier": "at_large"} for t in at_large_pool[:max(0, needed)]]

    field = auto_bids + at_large
    if len(field) < NCAA_FIELD_SIZE:
        raise ValueError(
            f"Only {len(field)} eligible level-3 teams with a record — a 64-team "
            f"NCAA field needs at least {NCAA_FIELD_SIZE}. Simulate more of the "
            f"regular season first."
        )

    # Overall selection seed (best record first).  If there are more auto-bids
    # than 64 (never with 29 conferences) the weakest champs drop off here.
    field.sort(key=lambda x: (x["win_pct"], x["conf_win_pct"], x["wins"]), reverse=True)
    field = field[:NCAA_FIELD_SIZE]

    for i, t in enumerate(field):
        t["seed"] = i + 1
        t["national_seed"] = (i + 1) if i < NCAA_NATIONAL_SEEDS else None

    # National seed n anchors regional n at regional_seed 1.
    for n in range(1, NCAA_NUM_REGIONALS + 1):
        anchor = field[n - 1]
        anchor["regional_no"] = n
        anchor["regional_seed"] = 1

    # Snake-draft the remaining 48 (already strongest-first) into seeds 2/3/4.
    # Seed 2 goes strongest-#2 -> weakest regional (16) down to weakest-#2 ->
    # regional 1, then snake back for seed 3, and again for seed 4.
    rest = field[NCAA_NUM_REGIONALS:]
    snake = {2: range(16, 0, -1), 3: range(1, 17), 4: range(16, 0, -1)}
    idx = 0
    for rseed in (2, 3, 4):
        for n in snake[rseed]:
            t = rest[idx]
            idx += 1
            t["regional_no"] = n
            t["regional_seed"] = rseed

    return field


def create_cws_bracket(
    conn,
    league_year_id: int,
    field: List[Dict],
    start_week: int = 40,
) -> Dict[str, Any]:
    """
    Persist the 64-team field to ``cws_bracket`` and create the 32 regional
    opening games (two per regional: #1 v #4 and #2 v #3, Bo1).

    Regionals start after the latest already-scheduled level-3 playoff game
    (i.e. after the conference tournaments), never before ``start_week``.
    """
    existing = conn.execute(sa_text("""
        SELECT COUNT(*) FROM cws_bracket WHERE league_year_id = :lyid
    """), {"lyid": league_year_id}).scalar()
    if existing:
        raise ValueError(
            "CWS bracket already exists for this league year — "
            "wipe playoffs (College / level 3) before regenerating."
        )

    for t in field:
        conn.execute(sa_text("""
            INSERT INTO cws_bracket
                (league_year_id, team_id, seed, qualification, losses,
                 eliminated, bracket_side, national_seed, regional_no,
                 regional_seed, stage)
            VALUES
                (:lyid, :tid, :seed, :qual, 0, 0, 'winners',
                 :nseed, :rno, :rseed, 'regional')
        """), {
            "lyid": league_year_id, "tid": t["team_id"], "seed": t["seed"],
            "qual": t.get("qualifier", "at_large"),
            "nseed": t.get("national_seed"),
            "rno": t["regional_no"], "rseed": t["regional_seed"],
        })

    reg_week = max(start_week, _ncaa_next_week(conn, league_year_id, start_week))

    by_reg: Dict[int, Dict[int, Dict]] = {}
    for t in field:
        by_reg.setdefault(t["regional_no"], {})[t["regional_seed"]] = t

    created: List[Dict] = []
    for n in range(1, NCAA_NUM_REGIONALS + 1):
        seeds = by_reg.get(n, {})
        if len(seeds) < 4:
            continue
        for snum, (sa_, sb_) in enumerate([(1, 4), (2, 3)], start=1):
            ta = {"team_id": seeds[sa_]["team_id"], "seed": sa_}
            tb = {"team_id": seeds[sb_]["team_id"], "seed": sb_}
            created.append(_create_group_series(
                conn, league_year_id, "REG_G1", f"R{n:02d}", snum,
                ta, tb, reg_week,
            ))

    log.info(
        "NCAA bracket: created %d regional opening games for league_year %d "
        "(regionals start week %d)", len(created), league_year_id, reg_week,
    )
    return {"series_created": created, "bracket_size": len(field),
            "regionals": NCAA_NUM_REGIONALS, "start_week": reg_week}


# ---------------------------------------------------------------------------
# Shared helpers for the multi-stage tournament
# ---------------------------------------------------------------------------

def _ncaa_next_week(conn, league_year_id: int, default: int) -> int:
    """Week after the latest already-scheduled level-3 playoff game."""
    row = conn.execute(sa_text("""
        SELECT MAX(gl.season_week) AS mw FROM gamelist gl
        WHERE gl.game_type = 'playoff' AND gl.league_level = 3
          AND gl.season = (
              SELECT s.id FROM seasons s
              JOIN league_years ly ON ly.league_year = s.year
              WHERE ly.id = :lyid LIMIT 1)
    """), {"lyid": league_year_id}).mappings().first()
    return (int(row["mw"]) + 1) if row and row["mw"] is not None else default


def _create_group_series(
    conn, league_year_id: int, round_name: str, group_key: Optional[str],
    series_number: int, team_a: Dict, team_b: Dict, start_week: int,
    series_length: int = 1,
) -> Dict[str, Any]:
    """
    Insert one level-3 playoff series (``team_a`` is the home/higher side) and
    schedule game 1.  ``team_a``/``team_b`` are dicts with ``team_id`` + ``seed``.
    For Bo>1 only game 1 is created; the rest come from
    ``generate_next_series_game`` after each result, like every other series here.
    """
    conn.execute(sa_text("""
        INSERT INTO playoff_series
            (league_year_id, league_level, round, series_number,
             team_a_id, team_b_id, seed_a, seed_b,
             series_length, status, start_week, conference)
        VALUES
            (:lyid, 3, :rnd, :snum, :ta, :tb, :sa, :sb,
             :slen, 'pending', :week, :grp)
    """), {
        "lyid": league_year_id, "rnd": round_name, "snum": series_number,
        "ta": team_a["team_id"], "tb": team_b["team_id"],
        "sa": team_a["seed"], "sb": team_b["seed"],
        "slen": series_length, "week": start_week,
        "grp": group_key if group_key else None,
    })

    if series_length == 1:
        home, away = team_a["team_id"], team_b["team_id"]
    else:
        pattern = HOME_PATTERNS[series_length]
        home = team_a["team_id"] if pattern[0] else team_b["team_id"]
        away = team_b["team_id"] if pattern[0] else team_a["team_id"]

    week, subweek = _next_available_subweek(
        conn, league_year_id, 3, team_a["team_id"], team_b["team_id"], start_week)
    _insert_single_playoff_game(conn, league_year_id, 3, home, away, week, subweek)

    return {"round": round_name, "group": group_key,
            "matchup": f"#{team_a['seed']} vs #{team_b['seed']}"}


def _de_results(conn, league_year_id: int, round_name: str, group_key: str) -> List[Dict]:
    """Winner/loser info for every completed series in (round_name, group_key)."""
    rows = conn.execute(sa_text("""
        SELECT series_number, team_a_id, team_b_id, seed_a, seed_b, winner_team_id
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3
          AND round = :rnd AND conference = :grp AND status = 'complete'
        ORDER BY series_number
    """), {"lyid": league_year_id, "rnd": round_name, "grp": group_key}).mappings().all()

    out = []
    for r in rows:
        winner_id = int(r["winner_team_id"])
        a_id, b_id = int(r["team_a_id"]), int(r["team_b_id"])
        if winner_id == a_id:
            loser_id, w_seed, l_seed = b_id, int(r["seed_a"]), int(r["seed_b"])
        else:
            loser_id, w_seed, l_seed = a_id, int(r["seed_b"]), int(r["seed_a"])
        out.append({
            "winner_id": winner_id, "loser_id": loser_id,
            "winner_seed": w_seed, "loser_seed": l_seed,
            "series_number": int(r["series_number"]),
        })
    return out


def _de_update_bracket(
    conn, league_year_id: int, team_ids: List[int], *, eliminate: bool = False,
) -> None:
    """Add a loss to each team; ``eliminate`` marks them out of the tournament.
    Guarded by ``eliminated = 0`` so re-running a transition is a no-op."""
    for tid in team_ids:
        if eliminate:
            conn.execute(sa_text("""
                UPDATE cws_bracket
                SET losses = losses + 1, bracket_side = 'eliminated',
                    eliminated = 1, stage = 'eliminated'
                WHERE league_year_id = :lyid AND team_id = :tid AND eliminated = 0
            """), {"lyid": league_year_id, "tid": tid})
        else:
            conn.execute(sa_text("""
                UPDATE cws_bracket
                SET losses = losses + 1, bracket_side = 'losers'
                WHERE league_year_id = :lyid AND team_id = :tid AND eliminated = 0
            """), {"lyid": league_year_id, "tid": tid})


def _set_stage(
    conn, league_year_id: int, team_ids: List[int], stage: str, *, reset: bool = False,
) -> None:
    """Set the current ``stage`` for teams.  ``reset`` clears loss state for a
    fresh double-elim group (MCWS entry)."""
    for tid in team_ids:
        if reset:
            conn.execute(sa_text("""
                UPDATE cws_bracket
                SET stage = :st, losses = 0, bracket_side = 'winners', eliminated = 0
                WHERE league_year_id = :lyid AND team_id = :tid
            """), {"st": stage, "lyid": league_year_id, "tid": tid})
        else:
            conn.execute(sa_text("""
                UPDATE cws_bracket SET stage = :st
                WHERE league_year_id = :lyid AND team_id = :tid
            """), {"st": stage, "lyid": league_year_id, "tid": tid})


def _set_eliminated(conn, league_year_id: int, team_ids: List[int]) -> None:
    """Mark teams eliminated (used for super-regional / finals losers)."""
    for tid in team_ids:
        conn.execute(sa_text("""
            UPDATE cws_bracket
            SET eliminated = 1, stage = 'eliminated', bracket_side = 'eliminated'
            WHERE league_year_id = :lyid AND team_id = :tid AND eliminated = 0
        """), {"lyid": league_year_id, "tid": tid})


def _bracket_seed(conn, league_year_id: int, team_id: int) -> int:
    row = conn.execute(sa_text("""
        SELECT seed FROM cws_bracket WHERE league_year_id = :lyid AND team_id = :tid
    """), {"lyid": league_year_id, "tid": team_id}).first()
    return int(row[0]) if row else 999


def _de_group_champion(conn, league_year_id: int, group_key: str) -> Optional[int]:
    """The lone non-eliminated team among a group's participants, else None."""
    rows = conn.execute(sa_text("""
        SELECT cb.team_id FROM cws_bracket cb
        WHERE cb.league_year_id = :lyid AND cb.eliminated = 0
          AND cb.team_id IN (
              SELECT team_a_id FROM playoff_series
              WHERE league_year_id = :lyid AND league_level = 3 AND conference = :grp
              UNION
              SELECT team_b_id FROM playoff_series
              WHERE league_year_id = :lyid AND league_level = 3 AND conference = :grp)
    """), {"lyid": league_year_id, "grp": group_key}).all()
    return int(rows[0][0]) if len(rows) == 1 else None


def _order_two(a: Dict, b: Dict) -> Tuple[Dict, Dict]:
    """Higher seed (lower number) first — that team hosts."""
    return (a, b) if a["seed"] <= b["seed"] else (b, a)


def _has_round_prefix(conn, league_year_id: int, prefix: str) -> bool:
    return bool(conn.execute(sa_text("""
        SELECT 1 FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3 AND round LIKE :like
        LIMIT 1
    """), {"lyid": league_year_id, "like": prefix + "%"}).first())


def _final_exists(conn, league_year_id: int) -> bool:
    return bool(conn.execute(sa_text("""
        SELECT 1 FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3 AND round = 'FINAL'
        LIMIT 1
    """), {"lyid": league_year_id}).first())


def _group_complete(conn, league_year_id: int, group_key: str) -> bool:
    """A 4-team group is done when nothing is pending/active and a champion
    (lone survivor) exists."""
    live = conn.execute(sa_text("""
        SELECT COUNT(*) FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3 AND conference = :grp
          AND status IN ('pending', 'active')
    """), {"lyid": league_year_id, "grp": group_key}).scalar()
    if int(live or 0) != 0:
        return False
    return _de_group_champion(conn, league_year_id, group_key) is not None


def _all_regionals_complete(conn, league_year_id: int) -> bool:
    return all(
        _group_complete(conn, league_year_id, f"R{n:02d}")
        for n in range(1, NCAA_NUM_REGIONALS + 1)
    )


def _all_super_complete(conn, league_year_id: int) -> bool:
    row = conn.execute(sa_text("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS done
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3 AND round = 'SUP'
    """), {"lyid": league_year_id}).mappings().first()
    total = int(row["total"] or 0)
    return total > 0 and total == int(row["done"] or 0)


def _all_mcws_complete(conn, league_year_id: int) -> bool:
    return (_group_complete(conn, league_year_id, "MCWS_A")
            and _group_complete(conn, league_year_id, "MCWS_B"))


# ---------------------------------------------------------------------------
# Generic 4-team double-elimination engine (regionals + MCWS brackets)
# ---------------------------------------------------------------------------

def _de_advance_group(
    conn, league_year_id: int, prefix: str, group_key: str,
) -> List[Dict]:
    """
    Advance one 4-team double-elimination group by (at most) one layer.

    ``prefix`` is 'REG' (a regional) or 'MCWS' (an Omaha bracket); ``group_key``
    is the ``conference`` value that scopes the group ('R01'..'R16' /
    'MCWS_A'/'MCWS_B').  Idempotent: each transition is skipped once its target
    round exists.  Returns the list of series created this call.
    """
    lyid = league_year_id

    def rn(suffix: str) -> str:
        return f"{prefix}_{suffix}"

    rows = conn.execute(sa_text("""
        SELECT round, status FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3 AND conference = :grp
    """), {"lyid": lyid, "grp": group_key}).mappings().all()
    if not rows:
        return []

    st: Dict[str, Dict[str, int]] = {}
    for r in rows:
        d = st.setdefault(r["round"], {"total": 0, "done": 0})
        d["total"] += 1
        if r["status"] == "complete":
            d["done"] += 1

    def done(suffix: str) -> bool:
        d = st.get(rn(suffix))
        return bool(d) and d["total"] == d["done"]

    def exists(suffix: str) -> bool:
        return rn(suffix) in st

    def next_week(*suffixes: str) -> int:
        rounds = [rn(s) for s in suffixes]
        ph = ", ".join(f":r{i}" for i in range(len(rounds)))
        p: Dict[str, Any] = {"lyid": lyid, "grp": group_key}
        for i, rr in enumerate(rounds):
            p[f"r{i}"] = rr
        row = conn.execute(sa_text(f"""
            SELECT MAX(start_week) AS mw FROM playoff_series
            WHERE league_year_id = :lyid AND league_level = 3 AND conference = :grp
              AND round IN ({ph})
        """), p).mappings().first()
        return (int(row["mw"]) + 1) if row and row["mw"] is not None else 40

    created: List[Dict] = []

    # G1 done -> WF (winners) + LB (losers)
    if done("G1") and not exists("WF"):
        res = _de_results(conn, lyid, rn("G1"), group_key)
        _de_update_bracket(conn, lyid, [r["loser_id"] for r in res])
        winners = sorted(
            [{"team_id": r["winner_id"], "seed": r["winner_seed"]} for r in res],
            key=lambda t: t["seed"])
        losers = sorted(
            [{"team_id": r["loser_id"], "seed": r["loser_seed"]} for r in res],
            key=lambda t: t["seed"])
        wk = next_week("G1")
        if len(winners) == 2:
            created.append(_create_group_series(
                conn, lyid, rn("WF"), group_key, 1, winners[0], winners[1], wk))
        if len(losers) == 2:
            created.append(_create_group_series(
                conn, lyid, rn("LB"), group_key, 1, losers[0], losers[1], wk))

    # WF + LB done -> L2 (WF loser drops down vs LB winner)
    if done("WF") and done("LB") and not exists("L2"):
        wf = _de_results(conn, lyid, rn("WF"), group_key)[0]
        lb = _de_results(conn, lyid, rn("LB"), group_key)[0]
        _de_update_bracket(conn, lyid, [wf["loser_id"]])
        _de_update_bracket(conn, lyid, [lb["loser_id"]], eliminate=True)
        drop = {"team_id": wf["loser_id"], "seed": wf["loser_seed"]}
        surv = {"team_id": lb["winner_id"], "seed": lb["winner_seed"]}
        a, b = _order_two(drop, surv)
        created.append(_create_group_series(
            conn, lyid, rn("L2"), group_key, 1, a, b, next_week("WF", "LB")))

    # L2 done -> RF (undefeated WF winner vs L2 winner); team_a = undefeated
    if done("WF") and done("L2") and not exists("RF"):
        wf = _de_results(conn, lyid, rn("WF"), group_key)[0]
        l2 = _de_results(conn, lyid, rn("L2"), group_key)[0]
        _de_update_bracket(conn, lyid, [l2["loser_id"]], eliminate=True)
        undef = {"team_id": wf["winner_id"], "seed": wf["winner_seed"]}
        surv = {"team_id": l2["winner_id"], "seed": l2["winner_seed"]}
        created.append(_create_group_series(
            conn, lyid, rn("RF"), group_key, 1, undef, surv, next_week("L2")))

    # RF done -> RF2 (if the losers-bracket team won) or finalize
    if done("RF") and not exists("RF2"):
        rf = conn.execute(sa_text("""
            SELECT team_a_id, team_b_id, seed_a, seed_b, winner_team_id
            FROM playoff_series
            WHERE league_year_id = :lyid AND league_level = 3
              AND conference = :grp AND round = :rnd AND status = 'complete'
            LIMIT 1
        """), {"lyid": lyid, "grp": group_key, "rnd": rn("RF")}).mappings().first()
        if rf:
            undef_id = int(rf["team_a_id"])
            winner_id = int(rf["winner_team_id"])
            if winner_id == undef_id:
                # Undefeated side won — group decided; eliminate the loser.
                _de_update_bracket(conn, lyid, [int(rf["team_b_id"])], eliminate=True)
            else:
                # Losers-bracket team won — undefeated takes its 1st loss; decider.
                _de_update_bracket(conn, lyid, [undef_id])
                undef = {"team_id": undef_id, "seed": int(rf["seed_a"])}
                surv = {"team_id": winner_id, "seed": int(rf["seed_b"])}
                created.append(_create_group_series(
                    conn, lyid, rn("RF2"), group_key, 1, surv, undef, next_week("RF")))

    # RF2 done -> finalize (eliminate the decider's loser)
    if done("RF2"):
        rf2 = _de_results(conn, lyid, rn("RF2"), group_key)
        if rf2:
            _de_update_bracket(conn, lyid, [rf2[0]["loser_id"]], eliminate=True)

    return created


# ---------------------------------------------------------------------------
# Stage builders
# ---------------------------------------------------------------------------

def _build_super_regionals(conn, league_year_id: int) -> List[Dict]:
    """16 regional champions -> 8 best-of-3 super regionals.
    Pairing SR_k = winner(R_k) vs winner(R_{17-k}); higher seed (R_k) hosts."""
    week = _ncaa_next_week(conn, league_year_id, 44)
    created: List[Dict] = []
    for k in range(1, 9):
        hi_no, lo_no = k, 17 - k
        hi = _de_group_champion(conn, league_year_id, f"R{hi_no:02d}")
        lo = _de_group_champion(conn, league_year_id, f"R{lo_no:02d}")
        if hi is None or lo is None:
            continue
        _set_stage(conn, league_year_id, [hi, lo], "super")
        created.append(_create_group_series(
            conn, league_year_id, "SUP", f"SR{k}", 1,
            {"team_id": hi, "seed": hi_no}, {"team_id": lo, "seed": lo_no},
            week, series_length=3))
    log.info("NCAA: built %d super regionals for league_year %d",
             len(created), league_year_id)
    return created


def _build_mcws(conn, league_year_id: int) -> List[Dict]:
    """8 super-regional winners -> two 4-team MCWS double-elim brackets."""
    sr_winner: Dict[int, int] = {}
    sr_loser: List[int] = []
    for k in range(1, 9):
        s = conn.execute(sa_text("""
            SELECT team_a_id, team_b_id, winner_team_id
            FROM playoff_series
            WHERE league_year_id = :lyid AND league_level = 3
              AND conference = :grp AND round = 'SUP' AND status = 'complete'
            LIMIT 1
        """), {"lyid": league_year_id, "grp": f"SR{k}"}).mappings().first()
        if not s:
            continue
        w = int(s["winner_team_id"])
        loser = int(s["team_b_id"]) if w == int(s["team_a_id"]) else int(s["team_a_id"])
        sr_winner[k] = w
        sr_loser.append(loser)
    _set_eliminated(conn, league_year_id, sr_loser)

    week = _ncaa_next_week(conn, league_year_id, 46)
    created: List[Dict] = []
    for grp_key, anchors in MCWS_BRACKET_ANCHORS.items():
        seeded = []
        for i, a in enumerate(sorted(anchors)):
            if a in sr_winner:
                seeded.append({"team_id": sr_winner[a], "seed": i + 1})
        _set_stage(conn, league_year_id, [t["team_id"] for t in seeded],
                   "mcws", reset=True)
        by_seed = {t["seed"]: t for t in seeded}
        for snum, (sa_, sb_) in enumerate([(1, 4), (2, 3)], start=1):
            if sa_ in by_seed and sb_ in by_seed:
                created.append(_create_group_series(
                    conn, league_year_id, "MCWS_G1", grp_key, snum,
                    by_seed[sa_], by_seed[sb_], week))
    log.info("NCAA: built MCWS (%d games) for league_year %d",
             len(created), league_year_id)
    return created


def _build_final(conn, league_year_id: int) -> List[Dict]:
    """Two MCWS bracket champions -> best-of-3 MCWS Finals."""
    a = _de_group_champion(conn, league_year_id, "MCWS_A")
    b = _de_group_champion(conn, league_year_id, "MCWS_B")
    if a is None or b is None:
        return []
    sa_ = _bracket_seed(conn, league_year_id, a)
    sb_ = _bracket_seed(conn, league_year_id, b)
    if sa_ <= sb_:
        hi, lo, hs, ls = a, b, sa_, sb_
    else:
        hi, lo, hs, ls = b, a, sb_, sa_
    _set_stage(conn, league_year_id, [a, b], "final")
    week = _ncaa_next_week(conn, league_year_id, 48)
    log.info("NCAA: built MCWS Finals for league_year %d", league_year_id)
    return [_create_group_series(
        conn, league_year_id, "FINAL", None, 1,
        {"team_id": hi, "seed": hs}, {"team_id": lo, "seed": ls},
        week, series_length=3)]


def _maybe_crown_champion(conn, league_year_id: int) -> Optional[int]:
    """If the MCWS Finals is complete, eliminate the runner-up and crown the
    champion (stage='champion').  Returns the champion team_id or None."""
    final = conn.execute(sa_text("""
        SELECT team_a_id, team_b_id, winner_team_id, status
        FROM playoff_series
        WHERE league_year_id = :lyid AND league_level = 3 AND round = 'FINAL'
        LIMIT 1
    """), {"lyid": league_year_id}).mappings().first()
    if not final or final["status"] != "complete" or not final["winner_team_id"]:
        return None
    winner = int(final["winner_team_id"])
    loser = (int(final["team_b_id"]) if winner == int(final["team_a_id"])
             else int(final["team_a_id"]))
    _set_eliminated(conn, league_year_id, [loser])
    conn.execute(sa_text("""
        UPDATE cws_bracket SET stage = 'champion'
        WHERE league_year_id = :lyid AND team_id = :tid
    """), {"lyid": league_year_id, "tid": winner})
    return winner


# ---------------------------------------------------------------------------
# NCAA tournament stage driver
# ---------------------------------------------------------------------------

def advance_cws_round(conn, league_year_id: int) -> Dict[str, Any]:
    """
    Advance the 64-team NCAA college tournament by one layer across all stages.

    Idempotent and safe to call repeatedly (the season "process & advance"
    cadence calls it each week): it advances every regional/MCWS bracket that
    has completed games, then builds the next stage once the current one fully
    resolves — Regionals -> Super Regionals -> MCWS -> Finals -> Champion.
    """
    lyid = league_year_id

    has_bracket = conn.execute(sa_text("""
        SELECT 1 FROM cws_bracket WHERE league_year_id = :lyid LIMIT 1
    """), {"lyid": lyid}).first()
    if not has_bracket and not _has_round_prefix(conn, lyid, "REG_"):
        return {"error": "No CWS bracket found"}

    created: List[Dict] = []

    # Stage 1 — advance each regional.
    if _has_round_prefix(conn, lyid, "REG_"):
        for n in range(1, NCAA_NUM_REGIONALS + 1):
            created += _de_advance_group(conn, lyid, "REG", f"R{n:02d}")

    # Stage 2 — all regionals done -> build super regionals.
    if (_has_round_prefix(conn, lyid, "REG_")
            and not _has_round_prefix(conn, lyid, "SUP")
            and _all_regionals_complete(conn, lyid)):
        created += _build_super_regionals(conn, lyid)

    # Stage 3 — all super regionals done -> build MCWS.
    if (_has_round_prefix(conn, lyid, "SUP")
            and not _has_round_prefix(conn, lyid, "MCWS_")
            and _all_super_complete(conn, lyid)):
        created += _build_mcws(conn, lyid)

    # Stage 4 — advance both MCWS brackets.
    if _has_round_prefix(conn, lyid, "MCWS_"):
        created += _de_advance_group(conn, lyid, "MCWS", "MCWS_A")
        created += _de_advance_group(conn, lyid, "MCWS", "MCWS_B")

    # Stage 5 — both MCWS brackets done -> build finals.
    if (_has_round_prefix(conn, lyid, "MCWS_")
            and not _final_exists(conn, lyid)
            and _all_mcws_complete(conn, lyid)):
        created += _build_final(conn, lyid)

    # Stage 6 — finals complete -> crown champion.
    champ = _maybe_crown_champion(conn, lyid)
    if champ is not None:
        return {"status": "complete", "champion": champ}

    if created:
        return {"series_created": created,
                "rounds_advanced": sorted({c["round"] for c in created})}

    return {"status": "in_progress",
            "message": "No actionable transitions — games may still be pending."}


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
                       'CT_R1','CT_R2','CT_R3','CT_R4','CT_R5',
                       'REG_G1','REG_WF','REG_LB','REG_L2','REG_RF','REG_RF2',
                       'SUP',
                       'MCWS_G1','MCWS_WF','MCWS_LB','MCWS_L2','MCWS_RF','MCWS_RF2',
                       'FINAL'),
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

    # Add CWS bracket state and conference tournament grouping if level 3
    if league_level == 3:
        # Group conference tournament rounds by conference
        ct_data: Dict[str, Dict] = {}
        ct_round_keys = [r for r in result["rounds"] if r.startswith(CT_ROUND_PREFIX)]
        for rnd_name in ct_round_keys:
            for s in result["rounds"][rnd_name]:
                conf = s["conference"]
                if conf:
                    ct_data.setdefault(conf, {"rounds": {}})
                    ct_data[conf]["rounds"].setdefault(rnd_name, []).append(s)
        for rnd_name in ct_round_keys:
            del result["rounds"][rnd_name]
        # Attach each conference's true bracket depth (from field size) so the
        # UI can label rounds correctly even while the tournament is in
        # progress (don't infer depth from the rounds that happen to exist yet).
        for conf in ct_data:
            n = conn.execute(sa_text("""
                SELECT COUNT(*) FROM conf_tournament_field
                WHERE league_year_id = :lyid AND conference = :conf
            """), {"lyid": league_year_id, "conf": conf}).scalar()
            ct_data[conf]["total_rounds"] = _ct_bracket_info(int(n or 0))["total_rounds"]
        result["conf_tournaments"] = ct_data

        cws = conn.execute(sa_text("""
            SELECT cb.*, t.team_abbrev
            FROM cws_bracket cb
            JOIN teams t ON t.id = cb.team_id
            WHERE cb.league_year_id = :lyid
            ORDER BY cb.seed
        """), {"lyid": league_year_id}).mappings().all()

        cws_rows = [{
            "team_id": int(c["team_id"]),
            "team_abbrev": c["team_abbrev"],
            "seed": int(c["seed"]),
            "qualification": c["qualification"],
            "losses": int(c["losses"]),
            "eliminated": bool(c["eliminated"]),
            "bracket_side": c["bracket_side"],
            "national_seed": int(c["national_seed"]) if c["national_seed"] is not None else None,
            "regional_no": int(c["regional_no"]) if c["regional_no"] is not None else None,
            "regional_seed": int(c["regional_seed"]) if c["regional_seed"] is not None else None,
            "stage": c["stage"],
        } for c in cws]
        result["cws_bracket"] = cws_rows

        # Restructure the NCAA rounds (REG_*, SUP, MCWS_*, FINAL) into the four
        # tournament stages the UI renders.  Pull them out of result["rounds"]
        # so the generic flat renderer (used for MLB/MiLB) ignores them.
        by_team = {r["team_id"]: r for r in cws_rows}

        def _pop_group(prefix, group):
            """Series for (round-prefix, conference=group), grouped by round, in
            REG/MCWS round order; also removes them from result['rounds']."""
            rounds = {}
            for rnd_name in list(result["rounds"].keys()):
                if not rnd_name.startswith(prefix):
                    continue
                keep = []
                for s in result["rounds"][rnd_name]:
                    if (s["conference"] or "") == group:
                        rounds.setdefault(rnd_name, []).append(s)
                    else:
                        keep.append(s)
                if keep:
                    result["rounds"][rnd_name] = keep
                else:
                    del result["rounds"][rnd_name]
            return rounds

        def _group_result(rounds):
            """(champion, complete) for a 4-team double-elim group, read from the
            deciding game's winner — robust even after that team later loses in a
            subsequent stage (so its cws_bracket row is eliminated)."""
            def _winner(suffix):
                key = next((k for k in rounds if k.endswith("_" + suffix)), None)
                if not key or not rounds[key]:
                    return None
                s = rounds[key][0]
                return s["winner"] if s.get("status") == "complete" else None
            rf2 = _winner("RF2")
            if rf2:
                return rf2, True
            rf_key = next((k for k in rounds if k.endswith("_RF")), None)
            rf2_exists = any(k.endswith("_RF2") for k in rounds)
            if rf_key and rounds[rf_key] and not rf2_exists:
                s = rounds[rf_key][0]
                if s.get("status") == "complete":
                    return s["winner"], True
            return None, False

        # --- Regionals (16) ---
        regionals = []
        for n in range(1, NCAA_NUM_REGIONALS + 1):
            group = f"R{n:02d}"
            teams = sorted(
                [r for r in cws_rows if r["regional_no"] == n],
                key=lambda r: (r["regional_seed"] or 9))
            rounds = _pop_group("REG_", group)
            champ, complete = _group_result(rounds)
            regionals.append({
                "regional_no": n, "group": group,
                "host": teams[0]["team_abbrev"] if teams else None,
                "national_seed": teams[0]["national_seed"] if teams else None,
                "teams": teams, "rounds": rounds,
                "champion": champ, "complete": complete,
            })

        # --- Super Regionals (up to 8) ---
        super_regionals = []
        sup_series = result["rounds"].pop("SUP", [])
        for s in sorted(sup_series, key=lambda s: s["conference"] or ""):
            super_regionals.append({**s, "sr": s["conference"]})

        # --- MCWS (two brackets) ---
        mcws = {}
        for side in ("A", "B"):
            group = f"MCWS_{side}"
            rounds = _pop_group("MCWS_", group)
            team_ids = sorted({
                s["team_a"]["id"] for r in rounds for s in rounds[r]
            } | {
                s["team_b"]["id"] for r in rounds for s in rounds[r]
            })
            teams = [by_team[t] for t in team_ids if t in by_team]
            champ, complete = _group_result(rounds)
            mcws[side] = {
                "group": group, "teams": teams, "rounds": rounds,
                "champion": champ, "complete": complete,
            }

        # --- Finals + overall champion ---
        final_list = result["rounds"].pop("FINAL", [])
        final = final_list[0] if final_list else None
        champ_row = next((r for r in cws_rows if r["stage"] == "champion"), None)
        champion = ({"id": champ_row["team_id"], "abbrev": champ_row["team_abbrev"]}
                    if champ_row else None)

        result["ncaa"] = {
            "regionals": regionals,
            "super_regionals": super_regionals,
            "mcws": mcws,
            "final": final,
            "champion": champion,
        }

    return result


# =====================================================================
# Full bracket skeleton (every round incl. TBD slots) for graphics
# =====================================================================
#
# Unlike get_bracket (which only returns series that already exist), this emits
# the COMPLETE bracket shape: every round through the final, with not-yet-played
# rounds as TBD placeholder slots.  Initial-round participants are read from the
# persisted seed tables (playoff_seeds / conf_tournament_field / cws_bracket) and
# the created series, so no standings recomputation is needed.  Future-round
# participants are left TBD because MLB and conference brackets RESEED each round
# (winners re-paired best-vs-worst) — there is no fixed feeder mapping to draw.
# Each bracket carries a ``kind`` so the renderer knows whether connector lines
# are meaningful: 'tree' (fixed single-elim, e.g. MiLB) vs 'reseed' / 'double_elim'.

# One 4-team double-elimination group (a regional or an MCWS bracket).
_DE_SKELETON_ROUNDS = [
    ("G1", "Round 1", 2),
    ("WF", "Winners' Final", 1),
    ("LB", "Elimination", 1),
    ("L2", "Losers' Final", 1),
    ("RF", "Final", 1),
    ("RF2", "If Necessary", 1),
]


def _sk_team(abbrev, seed):
    """A known bracket participant, or None for a TBD slot."""
    if abbrev is None:
        return None
    return {"abbrev": abbrev, "seed": int(seed) if seed else None}


def _sk_tbd(series_length, team_a=None, team_b=None):
    return {
        "series_id": None, "team_a": team_a, "team_b": team_b,
        "wins_a": 0, "wins_b": 0, "series_length": int(series_length),
        "status": "not_created", "winner": None, "games": [],
    }


def _sk_from_series(s, games_by_series=None):
    return {
        "series_id": int(s["id"]),
        "team_a": _sk_team(s["abbrev_a"], s["seed_a"]),
        "team_b": _sk_team(s["abbrev_b"], s["seed_b"]),
        "wins_a": int(s["wins_a"]),
        "wins_b": int(s["wins_b"]),
        "series_length": int(s["series_length"]),
        "status": s["status"],
        "winner": _sk_team(s["winner_abbrev"], None) if s["winner_team_id"] else None,
        # Per-game line scores from team_a's perspective: {a, b, win_a, win_b}.
        "games": (games_by_series or {}).get(int(s["id"]), []),
    }


def _sk_round(round_name, label, series_length, conf, inits, existing, games_by_series=None):
    """Overlay any created series for (round_name, conf) onto the TBD template."""
    rows = existing.get((round_name, conf or ""), [])
    matches = []
    for i, (a, b) in enumerate(inits):
        if i < len(rows):
            matches.append(_sk_from_series(rows[i], games_by_series))
        else:
            matches.append(_sk_tbd(series_length, a, b))
    # Defensive: more created series than the template expected — show them all.
    for j in range(len(inits), len(rows)):
        matches.append(_sk_from_series(rows[j], games_by_series))
    return {"round": round_name, "label": label, "matches": matches}


def _ct_label(rnd_num, total_rounds):
    if rnd_num == total_rounds:
        return "Final"
    if rnd_num == total_rounds - 1:
        return "Semifinal"
    if rnd_num == total_rounds - 2:
        return "Quarterfinal"
    return f"Round {rnd_num}"


def _sk_mlb_seedmap(conn, league_year_id):
    """{conf: {seed: abbrev}} from persisted seeds, falling back to the field."""
    out: Dict[str, Dict[int, str]] = {}
    try:
        prows = conn.execute(sa_text("""
            SELECT psd.conference, psd.seed, t.team_abbrev
            FROM playoff_seeds psd
            JOIN teams t ON t.id = psd.team_id
            WHERE psd.league_year_id = :lyid AND psd.league_level = 9
        """), {"lyid": league_year_id}).mappings().all()
        for r in prows:
            out.setdefault(r["conference"], {})[int(r["seed"])] = r["team_abbrev"]
    except Exception:
        out = {}
    if not out:
        try:
            field = determine_mlb_playoff_field(conn, league_year_id)
            for conf, teams in field.items():
                out[conf] = {int(t["seed"]): t["team_abbrev"] for t in teams}
        except Exception:
            pass
    return out


def _sk_build_mlb(conn, league_year_id, existing, games_by_series):
    if not any(rnd in ("WC", "DS", "CS", "WS") for (rnd, _c) in existing):
        return None
    seedmap = _sk_mlb_seedmap(conn, league_year_id)
    wc, ds, cs = [], [], []
    for conf in ("AL", "NL"):
        sm = seedmap.get(conf, {})
        wc += _sk_round("WC", "Wild Card", 3, conf, [
            (_sk_team(sm.get(3), 3), _sk_team(sm.get(6), 6)),
            (_sk_team(sm.get(4), 4), _sk_team(sm.get(5), 5)),
        ], existing, games_by_series)["matches"]
        ds += _sk_round("DS", "Division Series", 5, conf, [
            (_sk_team(sm.get(1), 1), None),
            (_sk_team(sm.get(2), 2), None),
        ], existing, games_by_series)["matches"]
        cs += _sk_round("CS", "Championship Series", 7, conf,
                        [(None, None)], existing, games_by_series)["matches"]
    ws = _sk_round("WS", "World Series", 7, "", [(None, None)], existing, games_by_series)
    rounds = [
        {"round": "WC", "label": "Wild Card", "matches": wc},
        {"round": "DS", "label": "Division Series", "matches": ds},
        {"round": "CS", "label": "Championship Series", "matches": cs},
        ws,
    ]
    return {"key": "main", "title": "MLB Playoffs", "kind": "reseed", "rounds": rounds}


def _sk_build_milb(existing, games_by_series):
    qf = existing.get(("QF", ""), [])
    if not qf:
        return None
    sm: Dict[int, str] = {}
    for s in qf:
        if s["seed_a"]:
            sm[int(s["seed_a"])] = s["abbrev_a"]
        if s["seed_b"]:
            sm[int(s["seed_b"])] = s["abbrev_b"]
    qf_inits = [
        (_sk_team(sm.get(1), 1), _sk_team(sm.get(8), 8)),
        (_sk_team(sm.get(2), 2), _sk_team(sm.get(7), 7)),
        (_sk_team(sm.get(3), 3), _sk_team(sm.get(6), 6)),
        (_sk_team(sm.get(4), 4), _sk_team(sm.get(5), 5)),
    ]
    rounds = [
        _sk_round("QF", "Quarterfinal", 7, "", qf_inits, existing, games_by_series),
        _sk_round("SF", "Semifinal", 7, "", [(None, None), (None, None)], existing, games_by_series),
        _sk_round("F", "Final", 7, "", [(None, None)], existing, games_by_series),
    ]
    return {"key": "main", "title": "Playoffs", "kind": "tree", "rounds": rounds}


def _sk_build_conferences(conn, league_year_id, existing, games_by_series):
    rows = conn.execute(sa_text("""
        SELECT ctf.conference, ctf.seed, ctf.has_bye, t.team_abbrev
        FROM conf_tournament_field ctf
        JOIN teams t ON t.id = ctf.team_id
        WHERE ctf.league_year_id = :lyid
        ORDER BY ctf.conference, ctf.seed
    """), {"lyid": league_year_id}).mappings().all()

    by_conf: Dict[str, List] = {}
    for r in rows:
        by_conf.setdefault(r["conference"], []).append(r)

    brackets = []
    for conf, teams in by_conf.items():
        info = _ct_bracket_info(len(teams))
        tr = info["total_rounds"]
        if tr == 0:
            continue
        num_byes = info["num_byes"]
        seed_ab = {int(t["seed"]): t["team_abbrev"] for t in teams}

        # Round 1: play-in among non-bye seeds (or everyone), paired best-vs-worst.
        if num_byes > 0:
            playing = sorted(int(t["seed"]) for t in teams if int(t["seed"]) > num_byes)
        else:
            playing = sorted(int(t["seed"]) for t in teams)
        r1_inits = []
        lo, hi = 0, len(playing) - 1
        while lo < hi:
            sa_, sb_ = playing[lo], playing[hi]
            r1_inits.append((_sk_team(seed_ab[sa_], sa_), _sk_team(seed_ab[sb_], sb_)))
            lo += 1
            hi -= 1
        rounds = [_sk_round("CT_R1", _ct_label(1, tr), 1, conf, r1_inits, existing, games_by_series)]

        # Round 2: the bye teams (known) re-enter here and are reseeded against
        # the R1 winners (TBD). The reseed sorts by seed and pairs best-vs-worst;
        # byes are the top seeds, so they always sort ahead of every R1 winner —
        # giving each bye a determinate R2 slot (and two byes can even meet).
        if tr >= 2:
            if num_byes > 0:
                bye_seeds = sorted(int(t["seed"]) for t in teams if int(t["seed"]) <= num_byes)
                participants = [_sk_team(seed_ab[s], s) for s in bye_seeds]
                participants += [None] * len(r1_inits)   # R1 winners — still TBD
                r2_inits = []
                lo, hi = 0, len(participants) - 1
                while lo < hi:
                    r2_inits.append((participants[lo], participants[hi]))
                    lo += 1
                    hi -= 1
            else:
                r2_inits = [(None, None)] * (1 << (tr - 2))
            rounds.append(_sk_round("CT_R2", _ct_label(2, tr), 1, conf, r2_inits, existing, games_by_series))

        # Round 3+ are all post-R2 winners — nothing determinate to show yet.
        for r in range(3, tr + 1):
            cnt = 1 << (tr - r)
            rounds.append(_sk_round(f"CT_R{r}", _ct_label(r, tr), 1, conf,
                                    [(None, None)] * cnt, existing, games_by_series))

        brackets.append({"key": conf, "title": f"{conf} Tournament",
                         "kind": "reseed", "rounds": rounds})
    return brackets


def _sk_build_cws(conn, league_year_id, existing, games_by_series):
    """
    Skeletons for the 64-team NCAA tournament — a LIST of brackets:
    16 regionals (4-team double-elim) + Super Regionals + two MCWS brackets +
    MCWS Finals.  Returns [] when nothing has been generated yet.
    """
    cws = conn.execute(sa_text("""
        SELECT cb.regional_no, cb.regional_seed, t.team_abbrev
        FROM cws_bracket cb
        JOIN teams t ON t.id = cb.team_id
        WHERE cb.league_year_id = :lyid
        ORDER BY cb.regional_no, cb.regional_seed
    """), {"lyid": league_year_id}).mappings().all()
    has_series = any(
        rnd.startswith("REG_") or rnd == "SUP" or rnd.startswith("MCWS_") or rnd == "FINAL"
        for (rnd, _c) in existing
    )
    if not cws and not has_series:
        return []

    reg_seed: Dict[int, Dict[int, str]] = {}
    reg_host: Dict[int, str] = {}
    for c in cws:
        if c["regional_no"] is None:
            continue
        rno = int(c["regional_no"])
        rseed = int(c["regional_seed"]) if c["regional_seed"] is not None else 0
        reg_seed.setdefault(rno, {})[rseed] = c["team_abbrev"]
        if rseed == 1:
            reg_host[rno] = c["team_abbrev"]

    def _de_bracket(prefix, group, key, title):
        rounds = []
        for suffix, label, count in _DE_SKELETON_ROUNDS:
            rname = f"{prefix}_{suffix}"
            if suffix == "G1" and prefix == "REG":
                sd = reg_seed.get(int(group[1:]), {})
                inits = [
                    (_sk_team(sd.get(1), 1), _sk_team(sd.get(4), 4)),
                    (_sk_team(sd.get(2), 2), _sk_team(sd.get(3), 3)),
                ]
            else:
                inits = [(None, None)] * count
            rounds.append(_sk_round(rname, label, 1, group, inits, existing, games_by_series))
        return {"key": key, "title": title, "kind": "double_elim", "rounds": rounds}

    brackets = []

    # Regionals (from the field, or from any created REG series).
    regional_nos = set(reg_seed.keys())
    for (rnd, conf) in existing:
        if rnd.startswith("REG_") and conf.startswith("R"):
            try:
                regional_nos.add(int(conf[1:]))
            except ValueError:
                pass
    for n in sorted(regional_nos):
        host = reg_host.get(n)
        title = f"Regional {n}" + (f" — {host}" if host else "")
        brackets.append(_de_bracket("REG", f"R{n:02d}", f"REG{n:02d}", title))

    # Super Regionals — one reseed column of up to 8 Bo3 series.
    sup_matches = []
    for k in range(1, 9):
        rows = existing.get(("SUP", f"SR{k}"), [])
        sup_matches.append(_sk_from_series(rows[0], games_by_series) if rows else _sk_tbd(3))
    brackets.append({"key": "SUPER", "title": "Super Regionals", "kind": "reseed",
                     "rounds": [{"round": "SUP", "label": "Super Regional (Bo3)",
                                 "matches": sup_matches}]})

    # MCWS brackets (two 4-team double-elims).
    brackets.append(_de_bracket("MCWS", "MCWS_A", "MCWS_A", "MCWS — Bracket A"))
    brackets.append(_de_bracket("MCWS", "MCWS_B", "MCWS_B", "MCWS — Bracket B"))

    # MCWS Finals (Bo3).
    fin_rows = existing.get(("FINAL", ""), [])
    fin_match = _sk_from_series(fin_rows[0], games_by_series) if fin_rows else _sk_tbd(3)
    brackets.append({"key": "FINAL", "title": "MCWS Finals", "kind": "reseed",
                     "rounds": [{"round": "FINAL", "label": "MCWS Finals (Bo3)",
                                 "matches": [fin_match]}]})

    return brackets


def _load_series_games(conn, league_year_id, league_level, series_rows):
    """
    Map each playoff series id → its ordered per-game line scores.

    There is no FK from games to playoff_series, so games are matched by the
    unordered team pair and sequenced by week/subweek.  When the same pair meets
    twice (CWS double-elim), each game is assigned to the most recent series of
    that pair whose start_week is at or before the game's week.  Scores are
    normalized to team_a's perspective: {a, b, win_a, win_b}.
    """
    games = conn.execute(sa_text("""
        SELECT gl.home_team AS home_id, gl.away_team AS away_id,
               gl.season_week, gl.season_subweek,
               gr.home_score, gr.away_score, gr.winning_team_id
        FROM gamelist gl
        JOIN game_results gr ON gr.game_id = gl.id
        WHERE gl.game_type = 'playoff' AND gl.league_level = :level
          AND gl.season = (
              SELECT s.id FROM seasons s
              JOIN league_years ly ON ly.league_year = s.year
              WHERE ly.id = :lyid LIMIT 1
          )
        ORDER BY gl.season_week, gl.season_subweek
    """), {"level": league_level, "lyid": league_year_id}).mappings().all()

    # Index series by unordered team pair, sorted by start_week.
    pair_series: Dict[frozenset, List] = {}
    for s in series_rows:
        key = frozenset((int(s["team_a_id"]), int(s["team_b_id"])))
        pair_series.setdefault(key, []).append(s)
    for lst in pair_series.values():
        lst.sort(key=lambda r: int(r["start_week"]))

    out: Dict[int, List] = {}
    for g in games:
        key = frozenset((int(g["home_id"]), int(g["away_id"])))
        cands = pair_series.get(key)
        if not cands:
            continue
        chosen = cands[0]
        for s in cands:
            if int(s["start_week"]) <= int(g["season_week"]):
                chosen = s
            else:
                break
        if int(g["home_id"]) == int(chosen["team_a_id"]):
            a, b = int(g["home_score"]), int(g["away_score"])
        else:
            a, b = int(g["away_score"]), int(g["home_score"])
        win = g["winning_team_id"]
        out.setdefault(int(chosen["id"]), []).append({
            "a": a, "b": b,
            "win_a": win is not None and int(win) == int(chosen["team_a_id"]),
            "win_b": win is not None and int(win) == int(chosen["team_b_id"]),
        })
    return out


def build_bracket_skeleton(conn, league_year_id: int, league_level: int) -> Dict[str, Any]:
    """
    Build the COMPLETE bracket structure (every round through the final,
    unplayed rounds as TBD slots) for graphic rendering.

    Returns ``{league_year_id, league_level, brackets: [{key, title, kind,
    rounds: [{round, label, matches: [slot]}]}]}``.  Each *slot* is either a
    real series (overlaid from playoff_series, including per-game ``games``
    scores) or a TBD placeholder.
    """
    rows = conn.execute(sa_text("""
        SELECT ps.*, ta.team_abbrev AS abbrev_a, tb.team_abbrev AS abbrev_b,
               tw.team_abbrev AS winner_abbrev
        FROM playoff_series ps
        JOIN teams ta ON ta.id = ps.team_a_id
        JOIN teams tb ON tb.id = ps.team_b_id
        LEFT JOIN teams tw ON tw.id = ps.winner_team_id
        WHERE ps.league_year_id = :lyid AND ps.league_level = :level
        ORDER BY ps.series_number
    """), {"lyid": league_year_id, "level": league_level}).mappings().all()

    existing: Dict[Tuple[str, str], List] = {}
    for s in rows:
        existing.setdefault((s["round"], s["conference"] or ""), []).append(s)

    games_by_series = _load_series_games(conn, league_year_id, league_level, rows)

    brackets: List[Dict] = []
    if league_level == 9:
        b = _sk_build_mlb(conn, league_year_id, existing, games_by_series)
        if b:
            brackets.append(b)
    elif 5 <= league_level <= 8:
        b = _sk_build_milb(existing, games_by_series)
        if b:
            brackets.append(b)
    elif league_level == 3:
        brackets.extend(_sk_build_conferences(conn, league_year_id, existing, games_by_series))
        brackets.extend(_sk_build_cws(conn, league_year_id, existing, games_by_series))

    return {
        "league_year_id": league_year_id,
        "league_level": league_level,
        "brackets": brackets,
    }


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
      - conf_tournament_field rows (level 3 only)

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
        "playoff_seeds": 0,
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

    # 2b. persisted seeds (optional table — skip if a pre-migration DB lacks it)
    if _table_exists(conn, "playoff_seeds"):
        res = conn.execute(sa_text("""
            DELETE FROM playoff_seeds
            WHERE league_year_id = :lyid AND league_level = :level
        """), params)
        deleted["playoff_seeds"] = res.rowcount

    # 3. cws_bracket + conf_tournament_field (level 3 only)
    if league_level == 3:
        res = conn.execute(sa_text("""
            DELETE FROM cws_bracket WHERE league_year_id = :lyid
        """), {"lyid": league_year_id})
        deleted["cws_bracket"] = res.rowcount

        res = conn.execute(sa_text("""
            DELETE FROM conf_tournament_field WHERE league_year_id = :lyid
        """), {"lyid": league_year_id})
        deleted["conf_tournament_field"] = res.rowcount

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


