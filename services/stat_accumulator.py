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
    game_type: str = "regular",
) -> Dict[str, int]:
    """
    Parse one game result and UPSERT player stats into the accumulation tables.
    Also inserts per-game batting/pitching lines for box score reconstruction.

    When game_type is 'allstar' or 'wbc', season accumulation UPSERTs are
    skipped but per-game lines are still written for box score reconstruction.

    Args:
        conn: Active SQLAlchemy connection (caller manages commit).
        game_result: Single entry from the engine's results array.
        league_year_id: Current league_year_id for the season context.
        game_type: Type of game ('regular', 'playoff', 'allstar', 'wbc').

    Returns:
        Dict with counts: {"batters": N, "pitchers": N, "fielders": N}
    """
    skip_season = game_type in ("allstar", "wbc")

    nested = game_result.get("result") or {}
    stats = game_result.get("stats") or nested.get("stats")
    if not stats:
        print(f"[stat_accumulator] NO stats found. Top keys={list(game_result.keys())}, nested keys={list(nested.keys())}")
        return {"batters": 0, "pitchers": 0, "fielders": 0}

    # game_id may be at top level OR nested inside "result"
    game_id = game_result.get("game_id") or nested.get("game_id")
    print(f"[stat_accumulator] game_id={game_id}, batters={len(stats.get('batters') or {})}, pitchers={len(stats.get('pitchers') or {})}")

    batters = stats.get("batters") or {}
    pitchers = stats.get("pitchers") or {}
    fielders = stats.get("fielders") or {}

    b_count = 0
    p_count = 0
    f_count = 0
    if not skip_season:
        b_count = _upsert_batting(conn, batters, league_year_id)
        p_count = _upsert_pitching(conn, pitchers, league_year_id)
        f_count = _upsert_fielding(conn, fielders, league_year_id)

    # Per-game lines for box score reconstruction
    if game_id is not None:
        gbl_count = _insert_game_batting_lines(conn, int(game_id), batters, league_year_id, fielders)
        gpl_count = _insert_game_pitching_lines(conn, int(game_id), pitchers, league_year_id)
        print(f"[stat_accumulator] game {game_id} per-game lines: {gbl_count} batting, {gpl_count} pitching")

        # Substitution tracking
        subs = game_result.get("substitutions") or nested.get("substitutions") or []
        sub_count = _insert_game_substitutions(conn, int(game_id), subs, league_year_id)
        if sub_count:
            print(f"[stat_accumulator] game {game_id} substitutions: {sub_count}")
    else:
        print(f"[stat_accumulator] game_id is NONE — skipping per-game lines. Top keys={list(game_result.keys())}, nested keys={list(nested.keys())}")

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

    print(f"[accumulate_subweek_stats] received {len(results)} results, league_year_id={league_year_id}")
    if results:
        first = results[0]
        print(f"[accumulate_subweek_stats] first result keys={list(first.keys())}")
        nested = first.get("result") or {}
        if nested:
            print(f"[accumulate_subweek_stats] first result['result'] keys={list(nested.keys())}")

    for game_result in results:
        game_id = game_result.get("game_id", "?")
        try:
            counts = accumulate_game_stats(conn, game_result, league_year_id)
            totals["batters"] += counts["batters"]
            totals["pitchers"] += counts["pitchers"]
            totals["fielders"] += counts["fielders"]
        except Exception as e:
            print(f"[accumulate_subweek_stats] EXCEPTION for game_id={game_id}: {e}")
            logger.exception(
                "stat_accumulator: failed for game_id=%s, skipping", game_id
            )

    logger.info(
        "stat_accumulator: subweek totals — %d batters, %d pitchers, %d fielders",
        totals["batters"], totals["pitchers"], totals["fielders"],
    )
    print(f"[accumulate_subweek_stats] DONE — totals={totals}")
    return totals


# ---------------------------------------------------------------------------
# Internal UPSERT helpers
# ---------------------------------------------------------------------------

_BATTING_UPSERT = text("""
    INSERT INTO player_batting_stats
        (player_id, league_year_id, team_id,
         games, at_bats, runs, hits, doubles_hit, triples,
         home_runs, inside_the_park_hr, rbi, walks, strikeouts,
         stolen_bases, caught_stealing)
    VALUES
        (:player_id, :league_year_id, :team_id,
         1, :at_bats, :runs, :hits, :doubles, :triples,
         :home_runs, :inside_the_park_hr, :rbi, :walks, :strikeouts,
         :stolen_bases, :caught_stealing)
    ON DUPLICATE KEY UPDATE
        games              = games + 1,
        at_bats            = at_bats + VALUES(at_bats),
        runs               = runs + VALUES(runs),
        hits               = hits + VALUES(hits),
        doubles_hit        = doubles_hit + VALUES(doubles_hit),
        triples            = triples + VALUES(triples),
        home_runs          = home_runs + VALUES(home_runs),
        inside_the_park_hr = inside_the_park_hr + VALUES(inside_the_park_hr),
        rbi                = rbi + VALUES(rbi),
        walks              = walks + VALUES(walks),
        strikeouts         = strikeouts + VALUES(strikeouts),
        stolen_bases       = stolen_bases + VALUES(stolen_bases),
        caught_stealing    = caught_stealing + VALUES(caught_stealing)
""")

_PITCHING_UPSERT = text("""
    INSERT INTO player_pitching_stats
        (player_id, league_year_id, team_id,
         games, games_started, wins, losses, saves,
         innings_pitched_outs, hits_allowed, runs_allowed, earned_runs,
         walks, strikeouts, home_runs_allowed, inside_the_park_hr_allowed)
    VALUES
        (:player_id, :league_year_id, :team_id,
         1, :games_started, :win, :loss, :save,
         :innings_pitched_outs, :hits_allowed, :runs_allowed, :earned_runs,
         :walks, :strikeouts, :home_runs_allowed, :inside_the_park_hr_allowed)
    ON DUPLICATE KEY UPDATE
        games                       = games + 1,
        games_started               = games_started + VALUES(games_started),
        wins                        = wins + VALUES(wins),
        losses                      = losses + VALUES(losses),
        saves                       = saves + VALUES(saves),
        innings_pitched_outs        = innings_pitched_outs + VALUES(innings_pitched_outs),
        hits_allowed                = hits_allowed + VALUES(hits_allowed),
        runs_allowed                = runs_allowed + VALUES(runs_allowed),
        earned_runs                 = earned_runs + VALUES(earned_runs),
        walks                       = walks + VALUES(walks),
        strikeouts                  = strikeouts + VALUES(strikeouts),
        home_runs_allowed           = home_runs_allowed + VALUES(home_runs_allowed),
        inside_the_park_hr_allowed  = inside_the_park_hr_allowed + VALUES(inside_the_park_hr_allowed)
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
                "player_id":          int(player_id_str),
                "league_year_id":     league_year_id,
                "team_id":            int(b["team_id"]),
                "at_bats":            int(b.get("at_bats", 0)),
                "runs":               int(b.get("runs", 0)),
                "hits":               int(b.get("hits", 0)),
                "doubles":            int(b.get("doubles", 0)),
                "triples":            int(b.get("triples", 0)),
                "home_runs":          int(b.get("home_runs", 0)),
                "inside_the_park_hr": int(b.get("inside_the_park_hr", 0)),
                "rbi":                int(b.get("rbi", 0)),
                "walks":              int(b.get("walks", 0)),
                "strikeouts":         int(b.get("strikeouts", 0)),
                "stolen_bases":       int(b.get("stolen_bases", 0)),
                "caught_stealing":    int(b.get("caught_stealing", 0)),
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
                "player_id":                   int(player_id_str),
                "league_year_id":              league_year_id,
                "team_id":                     int(p["team_id"]),
                "games_started":               int(p.get("games_started", 0)),
                "win":                         int(p.get("win", 0)),
                "loss":                        int(p.get("loss", 0)),
                "save":                        int(p.get("save", 0)),
                "innings_pitched_outs":        int(p.get("innings_pitched_outs", 0)),
                "hits_allowed":                int(p.get("hits_allowed", 0)),
                "runs_allowed":                int(p.get("runs_allowed", 0)),
                "earned_runs":                 int(p.get("earned_runs", 0)),
                "walks":                       int(p.get("walks", 0)),
                "strikeouts":                  int(p.get("strikeouts", 0)),
                "home_runs_allowed":           int(p.get("home_runs_allowed", 0)),
                "inside_the_park_hr_allowed":  int(p.get("inside_the_park_hr_allowed", 0)),
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
            # Engine returns keys as "playerid_position" (e.g. "42717_lf")
            # Split to extract player_id and position
            if "_" in player_id_str:
                pid_part, pos_part = player_id_str.rsplit("_", 1)
                player_id = int(pid_part)
                position_code = pos_part
            else:
                player_id = int(player_id_str)
                position_code = str(f.get("position_code", ""))

            conn.execute(_FIELDING_UPSERT, {
                "player_id":      player_id,
                "league_year_id": league_year_id,
                "team_id":        int(f["team_id"]),
                "position_code":  str(f.get("position_code", position_code)),
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
            try:
                conn.rollback()
            except Exception:
                pass
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


# ---------------------------------------------------------------------------
# Per-game line inserts (for box score reconstruction)
# ---------------------------------------------------------------------------

_GAME_BATTING_INSERT = text("""
    INSERT INTO game_batting_lines
        (game_id, player_id, team_id, league_year_id, position_code,
         at_bats, runs, hits, doubles_hit, triples,
         home_runs, inside_the_park_hr, rbi, walks, strikeouts,
         stolen_bases, caught_stealing, plate_appearances, hbp)
    VALUES
        (:game_id, :player_id, :team_id, :league_year_id, :position_code,
         :at_bats, :runs, :hits, :doubles, :triples,
         :home_runs, :inside_the_park_hr, :rbi, :walks, :strikeouts,
         :stolen_bases, :caught_stealing, :plate_appearances, :hbp)
    ON DUPLICATE KEY UPDATE
        position_code      = VALUES(position_code),
        at_bats            = VALUES(at_bats),
        runs               = VALUES(runs),
        hits               = VALUES(hits),
        doubles_hit        = VALUES(doubles_hit),
        triples            = VALUES(triples),
        home_runs          = VALUES(home_runs),
        inside_the_park_hr = VALUES(inside_the_park_hr),
        rbi                = VALUES(rbi),
        walks              = VALUES(walks),
        strikeouts         = VALUES(strikeouts),
        stolen_bases       = VALUES(stolen_bases),
        caught_stealing    = VALUES(caught_stealing),
        plate_appearances  = VALUES(plate_appearances),
        hbp                = VALUES(hbp)
""")

_GAME_PITCHING_INSERT = text("""
    INSERT INTO game_pitching_lines
        (game_id, player_id, team_id, league_year_id,
         games_started, win, loss, save_recorded,
         innings_pitched_outs, hits_allowed, runs_allowed, earned_runs,
         walks, strikeouts, home_runs_allowed, inside_the_park_hr_allowed,
         pitches_thrown, balls, strikes, hbp, wildpitches)
    VALUES
        (:game_id, :player_id, :team_id, :league_year_id,
         :games_started, :win, :loss, :save,
         :innings_pitched_outs, :hits_allowed, :runs_allowed, :earned_runs,
         :walks, :strikeouts, :home_runs_allowed, :inside_the_park_hr_allowed,
         :pitches_thrown, :balls, :strikes, :hbp, :wildpitches)
    ON DUPLICATE KEY UPDATE
        games_started               = VALUES(games_started),
        win                         = VALUES(win),
        loss                        = VALUES(loss),
        save_recorded               = VALUES(save_recorded),
        innings_pitched_outs        = VALUES(innings_pitched_outs),
        hits_allowed                = VALUES(hits_allowed),
        runs_allowed                = VALUES(runs_allowed),
        earned_runs                 = VALUES(earned_runs),
        walks                       = VALUES(walks),
        strikeouts                  = VALUES(strikeouts),
        home_runs_allowed           = VALUES(home_runs_allowed),
        inside_the_park_hr_allowed  = VALUES(inside_the_park_hr_allowed),
        pitches_thrown              = VALUES(pitches_thrown),
        balls                       = VALUES(balls),
        strikes                     = VALUES(strikes),
        hbp                         = VALUES(hbp),
        wildpitches                 = VALUES(wildpitches)
""")


def _insert_game_batting_lines(
    conn, game_id: int, batters: Dict[str, Any], league_year_id: int,
    fielders: Dict[str, Any] = None,
) -> int:
    # Build player_id → position lookup from fielders dict
    pos_map: Dict[int, str] = {}
    if fielders:
        for key in fielders:
            if "_" in key:
                pid_part, pos_part = key.rsplit("_", 1)
                try:
                    pos_map.setdefault(int(pid_part), pos_part)
                except ValueError:
                    pass

    count = 0
    for player_id_str, b in batters.items():
        try:
            pid = int(player_id_str)
            # Position from batter dict first, then fielders lookup
            pos = b.get("position") or pos_map.get(pid)
            conn.execute(_GAME_BATTING_INSERT, {
                "game_id":            game_id,
                "player_id":          pid,
                "team_id":            int(b["team_id"]),
                "league_year_id":     league_year_id,
                "position_code":      pos,
                "at_bats":            int(b.get("at_bats", 0)),
                "runs":               int(b.get("runs", 0)),
                "hits":               int(b.get("hits", 0)),
                "doubles":            int(b.get("doubles", 0)),
                "triples":            int(b.get("triples", 0)),
                "home_runs":          int(b.get("home_runs", 0)),
                "inside_the_park_hr": int(b.get("inside_the_park_hr", 0)),
                "rbi":                int(b.get("rbi", 0)),
                "walks":              int(b.get("walks", 0)),
                "strikeouts":         int(b.get("strikeouts", 0)),
                "stolen_bases":       int(b.get("stolen_bases", 0)),
                "caught_stealing":    int(b.get("caught_stealing", 0)),
                "plate_appearances":  int(b.get("plate_appearances", 0)),
                "hbp":                int(b.get("hbp", 0)),
            })
            count += 1
        except Exception as e:
            print(f"[stat_accumulator] BATTING INSERT FAILED game={game_id} player={player_id_str}: {e}")
            logger.exception(
                "stat_accumulator: game batting line insert failed for "
                "game %d player %s", game_id, player_id_str,
            )
    return count


def _insert_game_pitching_lines(
    conn, game_id: int, pitchers: Dict[str, Any], league_year_id: int
) -> int:
    count = 0
    for player_id_str, p in pitchers.items():
        try:
            conn.execute(_GAME_PITCHING_INSERT, {
                "game_id":                     game_id,
                "player_id":                   int(player_id_str),
                "team_id":                     int(p["team_id"]),
                "league_year_id":              league_year_id,
                "games_started":               int(p.get("games_started", 0)),
                "win":                         int(p.get("win", 0)),
                "loss":                        int(p.get("loss", 0)),
                "save":                        int(p.get("save", 0)),
                "innings_pitched_outs":        int(p.get("innings_pitched_outs", 0)),
                "hits_allowed":                int(p.get("hits_allowed", 0)),
                "runs_allowed":                int(p.get("runs_allowed", 0)),
                "earned_runs":                 int(p.get("earned_runs", 0)),
                "walks":                       int(p.get("walks", 0)),
                "strikeouts":                  int(p.get("strikeouts", 0)),
                "home_runs_allowed":           int(p.get("home_runs_allowed", 0)),
                "inside_the_park_hr_allowed":  int(p.get("inside_the_park_hr_allowed", 0)),
                "pitches_thrown":              int(p.get("pitches_thrown", 0)),
                "balls":                       int(p.get("balls", 0)),
                "strikes":                     int(p.get("strikes", 0)),
                "hbp":                         int(p.get("hbp", 0)),
                "wildpitches":                 int(p.get("wildpitches", 0)),
            })
            count += 1
        except Exception as e:
            print(f"[stat_accumulator] PITCHING INSERT FAILED game={game_id} player={player_id_str}: {e}")
            logger.exception(
                "stat_accumulator: game pitching line insert failed for "
                "game %d player %s", game_id, player_id_str,
            )
    return count


_GAME_SUBSTITUTION_INSERT = text("""
    INSERT INTO game_substitutions
        (game_id, league_year_id, inning, half, sub_type,
         player_in_id, player_out_id, new_position)
    VALUES
        (:game_id, :league_year_id, :inning, :half, :sub_type,
         :player_in_id, :player_out_id, :new_position)
""")


def _insert_game_substitutions(
    conn, game_id: int, substitutions: list, league_year_id: int
) -> int:
    count = 0
    for sub in substitutions:
        try:
            conn.execute(_GAME_SUBSTITUTION_INSERT, {
                "game_id":        game_id,
                "league_year_id": league_year_id,
                "inning":         int(sub.get("inning", 0)),
                "half":           str(sub.get("half", "")),
                "sub_type":       str(sub.get("type", "")),
                "player_in_id":   int(sub["player_in_id"]),
                "player_out_id":  int(sub["player_out_id"]),
                "new_position":   str(sub.get("new_position", "")),
            })
            count += 1
        except Exception as e:
            print(f"[stat_accumulator] SUBSTITUTION INSERT FAILED game={game_id}: {e}")
            logger.exception(
                "stat_accumulator: game substitution insert failed for "
                "game %d", game_id,
            )
    return count


# ---------------------------------------------------------------------------
# Bulk variants — collect all params across all games, execute once
# ---------------------------------------------------------------------------

def accumulate_subweek_stats_bulk(
    conn,
    results: List[Dict[str, Any]],
    league_year_id: int,
    game_type_by_id: Dict[int, str] = None,
) -> Dict[str, int]:
    """
    Bulk version of accumulate_subweek_stats.
    Collects all param dicts across all games, then executes each UPSERT
    statement once with executemany (list of param dicts).

    When game_type_by_id is provided, games with type 'allstar' or 'wbc'
    will only get per-game lines (box scores) but NOT season accumulation
    UPSERTs.
    """
    if game_type_by_id is None:
        game_type_by_id = {}

    # Season accumulation params (skipped for allstar/wbc)
    batting_params = []
    pitching_params = []
    fielding_params = []
    # Per-game lines (always written for box score reconstruction)
    game_batting_params = []
    game_pitching_params = []
    substitution_params = []

    # Types that should NOT accumulate into season stats
    NO_ACCUM_TYPES = {"allstar", "wbc"}

    for game_result in results:
        nested = game_result.get("result") or {}
        stats = game_result.get("stats") or nested.get("stats")
        if not stats:
            continue

        game_id = game_result.get("game_id") or nested.get("game_id")
        skip_season = game_type_by_id.get(int(game_id), "regular") in NO_ACCUM_TYPES if game_id is not None else False

        batters = stats.get("batters") or {}
        pitchers = stats.get("pitchers") or {}
        fielders = stats.get("fielders") or {}

        # Build player_id → position lookup from fielders dict
        pos_map: Dict[int, str] = {}
        for fkey in fielders:
            if "_" in fkey:
                pid_part, pos_part = fkey.rsplit("_", 1)
                try:
                    pos_map.setdefault(int(pid_part), pos_part)
                except ValueError:
                    pass

        # Batting season stats + per-game lines
        for pid_str, b in batters.items():
            try:
                pid = int(pid_str)
                params = {
                    "player_id":          pid,
                    "league_year_id":     league_year_id,
                    "team_id":            int(b["team_id"]),
                    "at_bats":            int(b.get("at_bats", 0)),
                    "runs":               int(b.get("runs", 0)),
                    "hits":               int(b.get("hits", 0)),
                    "doubles":            int(b.get("doubles", 0)),
                    "triples":            int(b.get("triples", 0)),
                    "home_runs":          int(b.get("home_runs", 0)),
                    "inside_the_park_hr": int(b.get("inside_the_park_hr", 0)),
                    "rbi":                int(b.get("rbi", 0)),
                    "walks":              int(b.get("walks", 0)),
                    "strikeouts":         int(b.get("strikeouts", 0)),
                    "stolen_bases":       int(b.get("stolen_bases", 0)),
                    "caught_stealing":    int(b.get("caught_stealing", 0)),
                }
                if not skip_season:
                    batting_params.append(params)

                if game_id is not None:
                    pos = b.get("position") or pos_map.get(pid)
                    game_batting_params.append({
                        "game_id": int(game_id),
                        "position_code": pos,
                        "plate_appearances": int(b.get("plate_appearances", 0)),
                        "hbp": int(b.get("hbp", 0)),
                        **params,
                    })
            except Exception:
                logger.exception(
                    "stat_accumulator bulk: failed to build batting params for %s", pid_str
                )

        # Pitching season stats + per-game lines
        for pid_str, p in pitchers.items():
            try:
                params = {
                    "player_id":                   int(pid_str),
                    "league_year_id":              league_year_id,
                    "team_id":                     int(p["team_id"]),
                    "games_started":               int(p.get("games_started", 0)),
                    "win":                         int(p.get("win", 0)),
                    "loss":                        int(p.get("loss", 0)),
                    "save":                        int(p.get("save", 0)),
                    "innings_pitched_outs":        int(p.get("innings_pitched_outs", 0)),
                    "hits_allowed":                int(p.get("hits_allowed", 0)),
                    "runs_allowed":                int(p.get("runs_allowed", 0)),
                    "earned_runs":                 int(p.get("earned_runs", 0)),
                    "walks":                       int(p.get("walks", 0)),
                    "strikeouts":                  int(p.get("strikeouts", 0)),
                    "home_runs_allowed":           int(p.get("home_runs_allowed", 0)),
                    "inside_the_park_hr_allowed":  int(p.get("inside_the_park_hr_allowed", 0)),
                }
                if not skip_season:
                    pitching_params.append(params)

                if game_id is not None:
                    game_pitching_params.append({
                        "game_id": int(game_id),
                        "pitches_thrown": int(p.get("pitches_thrown", 0)),
                        "balls": int(p.get("balls", 0)),
                        "strikes": int(p.get("strikes", 0)),
                        "hbp": int(p.get("hbp", 0)),
                        "wildpitches": int(p.get("wildpitches", 0)),
                        **params,
                    })
            except Exception:
                logger.exception(
                    "stat_accumulator bulk: failed to build pitching params for %s", pid_str
                )

        # Fielding season stats (skip for allstar/wbc)
        if not skip_season:
            for pid_str, f in fielders.items():
                try:
                    if "_" in pid_str:
                        pid_part, pos_part = pid_str.rsplit("_", 1)
                        player_id = int(pid_part)
                        position_code = pos_part
                    else:
                        player_id = int(pid_str)
                        position_code = str(f.get("position_code", ""))

                    fielding_params.append({
                        "player_id":      player_id,
                        "league_year_id": league_year_id,
                        "team_id":        int(f["team_id"]),
                        "position_code":  str(f.get("position_code", position_code)),
                        "innings":        int(f.get("innings", 0)),
                        "putouts":        int(f.get("putouts", 0)),
                        "assists":        int(f.get("assists", 0)),
                        "errors":         int(f.get("errors", 0)),
                    })
                except Exception:
                    logger.exception(
                        "stat_accumulator bulk: failed to build fielding params for %s", pid_str
                    )

        # Substitutions
        subs = game_result.get("substitutions") or nested.get("substitutions") or []
        if game_id is not None:
            for sub in subs:
                try:
                    substitution_params.append({
                        "game_id":        int(game_id),
                        "league_year_id": league_year_id,
                        "inning":         int(sub.get("inning", 0)),
                        "half":           str(sub.get("half", "")),
                        "sub_type":       str(sub.get("type", "")),
                        "player_in_id":   int(sub["player_in_id"]),
                        "player_out_id":  int(sub["player_out_id"]),
                        "new_position":   str(sub.get("new_position", "")),
                    })
                except Exception:
                    logger.exception(
                        "stat_accumulator bulk: failed to build substitution params for game %s",
                        game_id,
                    )

    # Execute each statement once with full param lists
    totals = {"batters": 0, "pitchers": 0, "fielders": 0}

    if batting_params:
        try:
            conn.execute(_BATTING_UPSERT, batting_params)
            totals["batters"] = len(batting_params)
        except Exception:
            logger.exception("stat_accumulator bulk: batting upsert failed (%d rows)", len(batting_params))

    if pitching_params:
        try:
            conn.execute(_PITCHING_UPSERT, pitching_params)
            totals["pitchers"] = len(pitching_params)
        except Exception:
            logger.exception("stat_accumulator bulk: pitching upsert failed (%d rows)", len(pitching_params))

    if fielding_params:
        try:
            conn.execute(_FIELDING_UPSERT, fielding_params)
            totals["fielders"] = len(fielding_params)
        except Exception:
            logger.exception("stat_accumulator bulk: fielding upsert failed (%d rows)", len(fielding_params))

    if game_batting_params:
        try:
            conn.execute(_GAME_BATTING_INSERT, game_batting_params)
        except Exception:
            logger.exception("stat_accumulator bulk: game batting insert failed (%d rows)", len(game_batting_params))

    if game_pitching_params:
        try:
            conn.execute(_GAME_PITCHING_INSERT, game_pitching_params)
        except Exception:
            logger.exception("stat_accumulator bulk: game pitching insert failed (%d rows)", len(game_pitching_params))

    if substitution_params:
        try:
            conn.execute(_GAME_SUBSTITUTION_INSERT, substitution_params)
        except Exception:
            logger.exception("stat_accumulator bulk: substitution insert failed (%d rows)", len(substitution_params))

    logger.info(
        "stat_accumulator bulk: %d batters, %d pitchers, %d fielders, "
        "%d game batting lines, %d game pitching lines, %d substitutions",
        totals["batters"], totals["pitchers"], totals["fielders"],
        len(game_batting_params), len(game_pitching_params),
        len(substitution_params),
    )
    return totals


def record_subweek_position_usage_bulk(
    conn,
    payloads: List[Dict[str, Any]],
    league_year_id: int,
) -> int:
    """
    Bulk version of record_subweek_position_usage.
    Collects all usage params, executes one executemany call.
    """
    usage_params = []

    for payload in payloads:
        season_week = payload.get("season_week")

        for side_key in ("home_side", "away_side"):
            side = payload.get(side_key) or {}
            defense = side.get("defense") or {}
            team_id = side.get("team_id")
            vs_hand = side.get("vs_hand")

            if not team_id or not vs_hand or vs_hand.upper() not in ("L", "R"):
                continue

            for def_key, usage_pos in _DEFENSE_POS_TO_USAGE.items():
                player_id = defense.get(def_key)
                if player_id is None:
                    continue

                usage_params.append({
                    "league_year_id": league_year_id,
                    "season_week":    season_week,
                    "team_id":        int(team_id),
                    "player_id":      int(player_id),
                    "position_code":  usage_pos,
                    "vs_hand":        vs_hand.upper(),
                })

    if not usage_params:
        return 0

    try:
        conn.execute(_USAGE_UPSERT, usage_params)
        logger.info("stat_accumulator bulk: %d position usage rows upserted", len(usage_params))
        return len(usage_params)
    except Exception:
        logger.exception(
            "stat_accumulator bulk: position usage upsert failed (%d rows)",
            len(usage_params),
        )
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
