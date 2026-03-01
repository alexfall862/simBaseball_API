# services/stat_accumulator.py
"""
Parses player box score stats from the game engine response and
UPSERTs them into the season accumulation tables:
  - player_batting_stats
  - player_pitching_stats
  - player_fielding_stats
  - player_position_usage_week  (defensive starts tracking)

Called from game_payload.build_week_payloads() after each subweek's
results come back from the engine.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy import text

logger = logging.getLogger("app")


def accumulate_game_stats(
    conn,
    game_result: Dict[str, Any],
    league_year_id: int,
) -> Dict[str, int]:
    """
    Parse one game result and UPSERT player stats into the accumulation tables.

    Args:
        conn: Active SQLAlchemy connection (caller manages commit).
        game_result: Single entry from the engine's results array.
        league_year_id: Current league_year_id for the season context.

    Returns:
        Dict with counts: {"batters": N, "pitchers": N, "fielders": N}
    """
    stats = game_result.get("stats")
    if not stats:
        return {"batters": 0, "pitchers": 0, "fielders": 0}

    batters = stats.get("batters") or {}
    pitchers = stats.get("pitchers") or {}
    fielders = stats.get("fielders") or {}

    b_count = _upsert_batting(conn, batters, league_year_id)
    p_count = _upsert_pitching(conn, pitchers, league_year_id)
    f_count = _upsert_fielding(conn, fielders, league_year_id)

    return {"batters": b_count, "pitchers": p_count, "fielders": f_count}


def accumulate_subweek_stats(
    conn,
    results: List[Dict[str, Any]],
    league_year_id: int,
) -> Dict[str, int]:
    """
    Accumulate stats for all games in a subweek.

    Args:
        conn: Active SQLAlchemy connection (caller manages commit).
        results: List of game results from the engine.
        league_year_id: Current league_year_id.

    Returns:
        Aggregate counts across all games.
    """
    totals = {"batters": 0, "pitchers": 0, "fielders": 0}

    for game_result in results:
        game_id = game_result.get("game_id", "?")
        try:
            counts = accumulate_game_stats(conn, game_result, league_year_id)
            totals["batters"] += counts["batters"]
            totals["pitchers"] += counts["pitchers"]
            totals["fielders"] += counts["fielders"]
        except Exception:
            logger.exception(
                "stat_accumulator: failed for game_id=%s, skipping", game_id
            )

    logger.info(
        "stat_accumulator: subweek totals — %d batters, %d pitchers, %d fielders",
        totals["batters"], totals["pitchers"], totals["fielders"],
    )
    return totals


# ---------------------------------------------------------------------------
# Internal UPSERT helpers
# ---------------------------------------------------------------------------

_BATTING_UPSERT = text("""
    INSERT INTO player_batting_stats
        (player_id, league_year_id, team_id,
         games, at_bats, runs, hits, doubles_hit, triples,
         home_runs, rbi, walks, strikeouts, stolen_bases, caught_stealing)
    VALUES
        (:player_id, :league_year_id, :team_id,
         1, :at_bats, :runs, :hits, :doubles, :triples,
         :home_runs, :rbi, :walks, :strikeouts, :stolen_bases, :caught_stealing)
    ON DUPLICATE KEY UPDATE
        games           = games + 1,
        at_bats         = at_bats + VALUES(at_bats),
        runs            = runs + VALUES(runs),
        hits            = hits + VALUES(hits),
        doubles_hit     = doubles_hit + VALUES(doubles_hit),
        triples         = triples + VALUES(triples),
        home_runs       = home_runs + VALUES(home_runs),
        rbi             = rbi + VALUES(rbi),
        walks           = walks + VALUES(walks),
        strikeouts      = strikeouts + VALUES(strikeouts),
        stolen_bases    = stolen_bases + VALUES(stolen_bases),
        caught_stealing = caught_stealing + VALUES(caught_stealing)
""")

_PITCHING_UPSERT = text("""
    INSERT INTO player_pitching_stats
        (player_id, league_year_id, team_id,
         games, games_started, wins, losses, saves,
         innings_pitched_outs, hits_allowed, runs_allowed, earned_runs,
         walks, strikeouts, home_runs_allowed)
    VALUES
        (:player_id, :league_year_id, :team_id,
         1, :games_started, :win, :loss, :save,
         :innings_pitched_outs, :hits_allowed, :runs_allowed, :earned_runs,
         :walks, :strikeouts, :home_runs_allowed)
    ON DUPLICATE KEY UPDATE
        games                = games + 1,
        games_started        = games_started + VALUES(games_started),
        wins                 = wins + VALUES(wins),
        losses               = losses + VALUES(losses),
        saves                = saves + VALUES(saves),
        innings_pitched_outs = innings_pitched_outs + VALUES(innings_pitched_outs),
        hits_allowed         = hits_allowed + VALUES(hits_allowed),
        runs_allowed         = runs_allowed + VALUES(runs_allowed),
        earned_runs          = earned_runs + VALUES(earned_runs),
        walks                = walks + VALUES(walks),
        strikeouts           = strikeouts + VALUES(strikeouts),
        home_runs_allowed    = home_runs_allowed + VALUES(home_runs_allowed)
""")

_FIELDING_UPSERT = text("""
    INSERT INTO player_fielding_stats
        (player_id, league_year_id, team_id, position_code,
         games, innings, putouts, assists, errors)
    VALUES
        (:player_id, :league_year_id, :team_id, :position_code,
         1, :innings, :putouts, :assists, :errors)
    ON DUPLICATE KEY UPDATE
        games   = games + 1,
        innings = innings + VALUES(innings),
        putouts = putouts + VALUES(putouts),
        assists = assists + VALUES(assists),
        errors  = errors + VALUES(errors)
""")


def _upsert_batting(
    conn, batters: Dict[str, Any], league_year_id: int
) -> int:
    count = 0
    for player_id_str, b in batters.items():
        try:
            conn.execute(_BATTING_UPSERT, {
                "player_id":       int(player_id_str),
                "league_year_id":  league_year_id,
                "team_id":         int(b["team_id"]),
                "at_bats":         int(b.get("at_bats", 0)),
                "runs":            int(b.get("runs", 0)),
                "hits":            int(b.get("hits", 0)),
                "doubles":         int(b.get("doubles", 0)),
                "triples":         int(b.get("triples", 0)),
                "home_runs":       int(b.get("home_runs", 0)),
                "rbi":             int(b.get("rbi", 0)),
                "walks":           int(b.get("walks", 0)),
                "strikeouts":      int(b.get("strikeouts", 0)),
                "stolen_bases":    int(b.get("stolen_bases", 0)),
                "caught_stealing": int(b.get("caught_stealing", 0)),
            })
            count += 1
        except Exception:
            logger.exception(
                "stat_accumulator: batting upsert failed for player %s",
                player_id_str,
            )
    return count


def _upsert_pitching(
    conn, pitchers: Dict[str, Any], league_year_id: int
) -> int:
    count = 0
    for player_id_str, p in pitchers.items():
        try:
            conn.execute(_PITCHING_UPSERT, {
                "player_id":            int(player_id_str),
                "league_year_id":       league_year_id,
                "team_id":              int(p["team_id"]),
                "games_started":        int(p.get("games_started", 0)),
                "win":                  int(p.get("win", 0)),
                "loss":                 int(p.get("loss", 0)),
                "save":                 int(p.get("save", 0)),
                "innings_pitched_outs": int(p.get("innings_pitched_outs", 0)),
                "hits_allowed":         int(p.get("hits_allowed", 0)),
                "runs_allowed":         int(p.get("runs_allowed", 0)),
                "earned_runs":          int(p.get("earned_runs", 0)),
                "walks":                int(p.get("walks", 0)),
                "strikeouts":           int(p.get("strikeouts", 0)),
                "home_runs_allowed":    int(p.get("home_runs_allowed", 0)),
            })
            count += 1
        except Exception:
            logger.exception(
                "stat_accumulator: pitching upsert failed for player %s",
                player_id_str,
            )
    return count


def _upsert_fielding(
    conn, fielders: Dict[str, Any], league_year_id: int
) -> int:
    count = 0
    for player_id_str, f in fielders.items():
        try:
            conn.execute(_FIELDING_UPSERT, {
                "player_id":      int(player_id_str),
                "league_year_id": league_year_id,
                "team_id":        int(f["team_id"]),
                "position_code":  str(f.get("position_code", "")),
                "innings":        int(f.get("innings", 0)),
                "putouts":        int(f.get("putouts", 0)),
                "assists":        int(f.get("assists", 0)),
                "errors":         int(f.get("errors", 0)),
            })
            count += 1
        except Exception:
            logger.exception(
                "stat_accumulator: fielding upsert failed for player %s",
                player_id_str,
            )
    return count


# ---------------------------------------------------------------------------
# Position usage tracking  (player_position_usage_week)
# ---------------------------------------------------------------------------

# Position codes in the defense dict that map to the usage table's enum.
# "startingpitcher" → "p"; all others match directly.
_DEFENSE_POS_TO_USAGE = {
    "startingpitcher": "p",
    "c": "c",
    "fb": "fb",
    "sb": "sb",
    "tb": "tb",
    "ss": "ss",
    "lf": "lf",
    "cf": "cf",
    "rf": "rf",
    "dh": "dh",
}

_USAGE_UPSERT = text("""
    INSERT INTO player_position_usage_week
        (league_year_id, season_week, team_id, player_id, position_code, vs_hand,
         starts_this_week)
    VALUES
        (:league_year_id, :season_week, :team_id, :player_id, :position_code, :vs_hand,
         1)
    ON DUPLICATE KEY UPDATE
        starts_this_week = starts_this_week + 1
""")


def record_game_position_usage(
    conn,
    defense: Dict[str, Any],
    team_id: int,
    vs_hand: str,
    league_year_id: int,
    season_week: int,
) -> int:
    """
    Record one defensive start per position assignment for a single team
    in a single game.

    Args:
        conn: Active SQLAlchemy connection (caller manages commit).
        defense: Position→player_id dict from the game payload.
        team_id: The team whose defense is being recorded.
        vs_hand: Opponent SP throw hand ('L' or 'R').
        league_year_id: Current league year.
        season_week: Current season week.

    Returns:
        Number of position rows upserted.
    """
    if not vs_hand or vs_hand.upper() not in ("L", "R"):
        logger.warning(
            "stat_accumulator: skipping usage tracking for team %d — "
            "invalid vs_hand=%r", team_id, vs_hand,
        )
        return 0

    count = 0
    for def_key, usage_pos in _DEFENSE_POS_TO_USAGE.items():
        player_id = defense.get(def_key)
        if player_id is None:
            continue
        try:
            conn.execute(_USAGE_UPSERT, {
                "league_year_id": league_year_id,
                "season_week":    season_week,
                "team_id":        team_id,
                "player_id":      int(player_id),
                "position_code":  usage_pos,
                "vs_hand":        vs_hand.upper(),
            })
            count += 1
        except Exception:
            logger.exception(
                "stat_accumulator: usage upsert failed for player %s "
                "at %s (team %d)", player_id, usage_pos, team_id,
            )
    return count


def record_subweek_position_usage(
    conn,
    payloads: List[Dict[str, Any]],
    league_year_id: int,
) -> int:
    """
    Record position usage for all games in a subweek.

    Reads the defense dict and vs_hand from each payload's home_side
    and away_side and UPSERTs a start into player_position_usage_week.

    Args:
        conn: Active SQLAlchemy connection (caller manages commit).
        payloads: List of game payloads (each containing home_side/away_side).
        league_year_id: Current league year.

    Returns:
        Total number of position rows upserted across all games.
    """
    total = 0
    for payload in payloads:
        game_id = payload.get("game_id", "?")
        season_week = payload.get("season_week")
        if season_week is None:
            logger.warning(
                "stat_accumulator: no season_week in payload for game %s, "
                "skipping usage tracking", game_id,
            )
            continue

        for side_key in ("home_side", "away_side"):
            side = payload.get(side_key) or {}
            defense = side.get("defense") or {}
            team_id = side.get("team_id")
            vs_hand = side.get("vs_hand")

            if not team_id or not defense:
                continue

            try:
                n = record_game_position_usage(
                    conn, defense, int(team_id), vs_hand,
                    league_year_id, int(season_week),
                )
                total += n
            except Exception:
                logger.exception(
                    "stat_accumulator: usage tracking failed for game %s "
                    "%s (team %s)", game_id, side_key, team_id,
                )

    logger.info(
        "stat_accumulator: subweek usage tracking — %d position rows upserted",
        total,
    )
    return total
