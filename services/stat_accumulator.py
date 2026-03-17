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

# Chunk size for executemany batching — keeps SQL statement size reasonable
# and reduces lock hold time on InnoDB.
_BULK_CHUNK_SIZE = 100


def _chunked_execute(conn, stmt, params: list, chunk_size: int = _BULK_CHUNK_SIZE) -> int:
    """Execute a statement in chunks to avoid oversized SQL and long lock holds."""
    total = 0
    for i in range(0, len(params), chunk_size):
        chunk = params[i:i + chunk_size]
        conn.execute(stmt, chunk)
        total += len(chunk)
    return total


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
    AS new_row ON DUPLICATE KEY UPDATE
        games              = player_batting_stats.games + 1,
        at_bats            = player_batting_stats.at_bats + new_row.at_bats,
        runs               = player_batting_stats.runs + new_row.runs,
        hits               = player_batting_stats.hits + new_row.hits,
        doubles_hit        = player_batting_stats.doubles_hit + new_row.doubles_hit,
        triples            = player_batting_stats.triples + new_row.triples,
        home_runs          = player_batting_stats.home_runs + new_row.home_runs,
        inside_the_park_hr = player_batting_stats.inside_the_park_hr + new_row.inside_the_park_hr,
        rbi                = player_batting_stats.rbi + new_row.rbi,
        walks              = player_batting_stats.walks + new_row.walks,
        strikeouts         = player_batting_stats.strikeouts + new_row.strikeouts,
        stolen_bases       = player_batting_stats.stolen_bases + new_row.stolen_bases,
        caught_stealing    = player_batting_stats.caught_stealing + new_row.caught_stealing
""")

_PITCHING_UPSERT = text("""
    INSERT INTO player_pitching_stats
        (player_id, league_year_id, team_id,
         games, games_started, wins, losses, saves,
         holds, blown_saves, quality_starts,
         innings_pitched_outs, hits_allowed, runs_allowed, earned_runs,
         walks, strikeouts, home_runs_allowed, inside_the_park_hr_allowed)
    VALUES
        (:player_id, :league_year_id, :team_id,
         1, :games_started, :win, :loss, :save,
         :hold, :blown_save, :quality_start,
         :innings_pitched_outs, :hits_allowed, :runs_allowed, :earned_runs,
         :walks, :strikeouts, :home_runs_allowed, :inside_the_park_hr_allowed)
    AS new_row ON DUPLICATE KEY UPDATE
        games                       = player_pitching_stats.games + 1,
        games_started               = player_pitching_stats.games_started + new_row.games_started,
        wins                        = player_pitching_stats.wins + new_row.wins,
        losses                      = player_pitching_stats.losses + new_row.losses,
        saves                       = player_pitching_stats.saves + new_row.saves,
        holds                       = player_pitching_stats.holds + new_row.holds,
        blown_saves                 = player_pitching_stats.blown_saves + new_row.blown_saves,
        quality_starts              = player_pitching_stats.quality_starts + new_row.quality_starts,
        innings_pitched_outs        = player_pitching_stats.innings_pitched_outs + new_row.innings_pitched_outs,
        hits_allowed                = player_pitching_stats.hits_allowed + new_row.hits_allowed,
        runs_allowed                = player_pitching_stats.runs_allowed + new_row.runs_allowed,
        earned_runs                 = player_pitching_stats.earned_runs + new_row.earned_runs,
        walks                       = player_pitching_stats.walks + new_row.walks,
        strikeouts                  = player_pitching_stats.strikeouts + new_row.strikeouts,
        home_runs_allowed           = player_pitching_stats.home_runs_allowed + new_row.home_runs_allowed,
        inside_the_park_hr_allowed  = player_pitching_stats.inside_the_park_hr_allowed + new_row.inside_the_park_hr_allowed
""")

_FIELDING_UPSERT = text("""
    INSERT INTO player_fielding_stats
        (player_id, league_year_id, team_id, position_code,
         games, innings, putouts, assists, errors)
    VALUES
        (:player_id, :league_year_id, :team_id, :position_code,
         1, :innings, :putouts, :assists, :errors)
    AS new_row ON DUPLICATE KEY UPDATE
        games   = player_fielding_stats.games + 1,
        innings = player_fielding_stats.innings + new_row.innings,
        putouts = player_fielding_stats.putouts + new_row.putouts,
        assists = player_fielding_stats.assists + new_row.assists,
        errors  = player_fielding_stats.errors + new_row.errors
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
                "hold":                        int(p.get("hold", 0)),
                "blown_save":                  int(p.get("blown_save", 0)),
                "quality_start":               int(p.get("quality_start", 0)),
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


_FIELDING_POS_NORMALIZE = {
    "startingpitcher": "p",
    "pitcher": "p",
    "catcher": "c",
    "first base": "fb",
    "second base": "sb",
    "third base": "tb",
    "shortstop": "ss",
    "left field": "lf",
    "center field": "cf",
    "right field": "rf",
}


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
                position_code = _FIELDING_POS_NORMALIZE.get(pos_part.lower(), pos_part)
            else:
                player_id = int(player_id_str)
                raw_pos = str(f.get("position_code", ""))
                position_code = _FIELDING_POS_NORMALIZE.get(raw_pos.lower(), raw_pos)

            conn.execute(_FIELDING_UPSERT, {
                "player_id":      player_id,
                "league_year_id": league_year_id,
                "team_id":        int(f["team_id"]),
                "position_code":  position_code[:16],
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

# Per-game line columns shared by both fresh and upsert variants
_GAME_BATTING_COLS = """(game_id, player_id, team_id, league_year_id, position_code,
         batting_order, at_bats, runs, hits, doubles_hit, triples,
         home_runs, inside_the_park_hr, rbi, walks, strikeouts,
         stolen_bases, caught_stealing, plate_appearances, hbp)"""

_GAME_BATTING_VALS = """(:game_id, :player_id, :team_id, :league_year_id, :position_code,
         :batting_order, :at_bats, :runs, :hits, :doubles, :triples,
         :home_runs, :inside_the_park_hr, :rbi, :walks, :strikeouts,
         :stolen_bases, :caught_stealing, :plate_appearances, :hbp)"""

# Fresh insert — no ON DUPLICATE KEY overhead (used for first-time simulation)
_GAME_BATTING_INSERT_FRESH = text(f"""
    INSERT INTO game_batting_lines {_GAME_BATTING_COLS}
    VALUES {_GAME_BATTING_VALS}
""")

# Upsert variant — used when re-simulating (rollback + replay)
_GAME_BATTING_INSERT = text(f"""
    INSERT INTO game_batting_lines {_GAME_BATTING_COLS}
    VALUES {_GAME_BATTING_VALS}
    AS new_row ON DUPLICATE KEY UPDATE
        position_code      = new_row.position_code,
        batting_order      = new_row.batting_order,
        at_bats            = new_row.at_bats,
        runs               = new_row.runs,
        hits               = new_row.hits,
        doubles_hit        = new_row.doubles_hit,
        triples            = new_row.triples,
        home_runs          = new_row.home_runs,
        inside_the_park_hr = new_row.inside_the_park_hr,
        rbi                = new_row.rbi,
        walks              = new_row.walks,
        strikeouts         = new_row.strikeouts,
        stolen_bases       = new_row.stolen_bases,
        caught_stealing    = new_row.caught_stealing,
        plate_appearances  = new_row.plate_appearances,
        hbp                = new_row.hbp
""")

_GAME_PITCHING_COLS = """(game_id, player_id, team_id, league_year_id,
         pitch_appearance_order,
         games_started, win, loss, save_recorded,
         hold, blown_save, quality_start,
         innings_pitched_outs, hits_allowed, runs_allowed, earned_runs,
         walks, strikeouts, home_runs_allowed, inside_the_park_hr_allowed,
         pitches_thrown, balls, strikes, hbp, wildpitches)"""

_GAME_PITCHING_VALS = """(:game_id, :player_id, :team_id, :league_year_id,
         :pitch_appearance_order,
         :games_started, :win, :loss, :save,
         :hold, :blown_save, :quality_start,
         :innings_pitched_outs, :hits_allowed, :runs_allowed, :earned_runs,
         :walks, :strikeouts, :home_runs_allowed, :inside_the_park_hr_allowed,
         :pitches_thrown, :balls, :strikes, :hbp, :wildpitches)"""

# Fresh insert — no ON DUPLICATE KEY overhead (used for first-time simulation)
_GAME_PITCHING_INSERT_FRESH = text(f"""
    INSERT INTO game_pitching_lines {_GAME_PITCHING_COLS}
    VALUES {_GAME_PITCHING_VALS}
""")

# Upsert variant — used when re-simulating (rollback + replay)
_GAME_PITCHING_INSERT = text(f"""
    INSERT INTO game_pitching_lines {_GAME_PITCHING_COLS}
    VALUES {_GAME_PITCHING_VALS}
    AS new_row ON DUPLICATE KEY UPDATE
        pitch_appearance_order      = new_row.pitch_appearance_order,
        games_started               = new_row.games_started,
        win                         = new_row.win,
        loss                        = new_row.loss,
        save_recorded               = new_row.save_recorded,
        hold                        = new_row.hold,
        blown_save                  = new_row.blown_save,
        quality_start               = new_row.quality_start,
        innings_pitched_outs        = new_row.innings_pitched_outs,
        hits_allowed                = new_row.hits_allowed,
        runs_allowed                = new_row.runs_allowed,
        earned_runs                 = new_row.earned_runs,
        walks                       = new_row.walks,
        strikeouts                  = new_row.strikeouts,
        home_runs_allowed           = new_row.home_runs_allowed,
        inside_the_park_hr_allowed  = new_row.inside_the_park_hr_allowed,
        pitches_thrown              = new_row.pitches_thrown,
        balls                       = new_row.balls,
        strikes                     = new_row.strikes,
        hbp                         = new_row.hbp,
        wildpitches                 = new_row.wildpitches
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
                "batting_order":      int(b.get("batting_order", 0)),
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
                "pitch_appearance_order":      int(p.get("pitch_appearance_order", 0)),
                "games_started":               int(p.get("games_started", 0)),
                "win":                         int(p.get("win", 0)),
                "loss":                        int(p.get("loss", 0)),
                "save":                        int(p.get("save", 0)),
                "hold":                        int(p.get("hold", 0)),
                "blown_save":                  int(p.get("blown_save", 0)),
                "quality_start":               int(p.get("quality_start", 0)),
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
         player_in_id, player_out_id, new_position,
         entry_score_diff, entry_runners_on, entry_inning,
         entry_outs, entry_is_save_situation)
    VALUES
        (:game_id, :league_year_id, :inning, :half, :sub_type,
         :player_in_id, :player_out_id, :new_position,
         :entry_score_diff, :entry_runners_on, :entry_inning,
         :entry_outs, :entry_is_save_situation)
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
                "entry_score_diff":       sub.get("entry_score_diff"),
                "entry_runners_on":       sub.get("entry_runners_on"),
                "entry_inning":           sub.get("entry_inning"),
                "entry_outs":             sub.get("entry_outs"),
                "entry_is_save_situation": 1 if sub.get("entry_is_save_situation") else (0 if "entry_is_save_situation" in sub else None),
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
    is_resim: bool = False,
) -> Dict[str, int]:
    """
    Bulk version of accumulate_subweek_stats.
    Collects all param dicts across all games, then executes each UPSERT
    statement once with executemany (list of param dicts).

    When game_type_by_id is provided, games with type 'allstar' or 'wbc'
    will only get per-game lines (box scores) but NOT season accumulation
    UPSERTs.

    Args:
        is_resim: If True, use ON DUPLICATE KEY UPDATE for per-game lines
                  (needed after rollback + replay).  If False, use plain
                  INSERT for per-game lines (faster for fresh simulation).
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
                        "batting_order": int(b.get("batting_order", 0)),
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
                    "hold":                        int(p.get("hold", 0)),
                    "blown_save":                  int(p.get("blown_save", 0)),
                    "quality_start":               int(p.get("quality_start", 0)),
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
                        "pitch_appearance_order": int(p.get("pitch_appearance_order", 0)),
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
                        position_code = _FIELDING_POS_NORMALIZE.get(pos_part.lower(), pos_part)
                    else:
                        player_id = int(pid_str)
                        raw_pos = str(f.get("position_code", ""))
                        position_code = _FIELDING_POS_NORMALIZE.get(raw_pos.lower(), raw_pos)

                    fielding_params.append({
                        "player_id":      player_id,
                        "league_year_id": league_year_id,
                        "team_id":        int(f["team_id"]),
                        "position_code":  position_code[:16],
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
                        "entry_score_diff":       sub.get("entry_score_diff"),
                        "entry_runners_on":       sub.get("entry_runners_on"),
                        "entry_inning":           sub.get("entry_inning"),
                        "entry_outs":             sub.get("entry_outs"),
                        "entry_is_save_situation": 1 if sub.get("entry_is_save_situation") else (0 if "entry_is_save_situation" in sub else None),
                    })
                except Exception:
                    logger.exception(
                        "stat_accumulator bulk: failed to build substitution params for game %s",
                        game_id,
                    )

    # Execute all bulk writes with FK checks disabled (data is pre-validated
    # from cache/engine results, so referential integrity is guaranteed).
    totals = {"batters": 0, "pitchers": 0, "fielders": 0}

    try:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))

        # --- Season accumulation UPSERTs (chunked) ---
        if batting_params:
            try:
                totals["batters"] = _chunked_execute(conn, _BATTING_UPSERT, batting_params)
            except Exception:
                logger.exception("stat_accumulator bulk: batting upsert failed (%d rows)", len(batting_params))

        if pitching_params:
            try:
                totals["pitchers"] = _chunked_execute(conn, _PITCHING_UPSERT, pitching_params)
            except Exception:
                logger.exception("stat_accumulator bulk: pitching upsert failed (%d rows)", len(pitching_params))

        if fielding_params:
            try:
                totals["fielders"] = _chunked_execute(conn, _FIELDING_UPSERT, fielding_params)
            except Exception:
                logger.exception("stat_accumulator bulk: fielding upsert failed (%d rows)", len(fielding_params))

        # --- Per-game lines: use fresh INSERT when possible, UPSERT for re-sims ---
        game_bat_stmt = _GAME_BATTING_INSERT if is_resim else _GAME_BATTING_INSERT_FRESH
        game_pitch_stmt = _GAME_PITCHING_INSERT if is_resim else _GAME_PITCHING_INSERT_FRESH

        if game_batting_params:
            try:
                _chunked_execute(conn, game_bat_stmt, game_batting_params)
            except Exception:
                if not is_resim:
                    # Fresh insert failed (likely duplicate from partial re-sim) — retry with upsert
                    logger.warning("stat_accumulator bulk: fresh batting insert failed, retrying with upsert")
                    try:
                        _chunked_execute(conn, _GAME_BATTING_INSERT, game_batting_params)
                    except Exception:
                        logger.exception("stat_accumulator bulk: game batting upsert also failed (%d rows)", len(game_batting_params))
                else:
                    logger.exception("stat_accumulator bulk: game batting insert failed (%d rows)", len(game_batting_params))

        if game_pitching_params:
            try:
                _chunked_execute(conn, game_pitch_stmt, game_pitching_params)
            except Exception:
                if not is_resim:
                    logger.warning("stat_accumulator bulk: fresh pitching insert failed, retrying with upsert")
                    try:
                        _chunked_execute(conn, _GAME_PITCHING_INSERT, game_pitching_params)
                    except Exception:
                        logger.exception("stat_accumulator bulk: game pitching upsert also failed (%d rows)", len(game_pitching_params))
                else:
                    logger.exception("stat_accumulator bulk: game pitching insert failed (%d rows)", len(game_pitching_params))

        if substitution_params:
            try:
                _chunked_execute(conn, _GAME_SUBSTITUTION_INSERT, substitution_params)
            except Exception:
                logger.exception("stat_accumulator bulk: substitution insert failed (%d rows)", len(substitution_params))

    finally:
        # Always re-enable FK checks, even if an exception occurred
        try:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        except Exception:
            logger.exception("stat_accumulator bulk: failed to re-enable FK checks")

    logger.info(
        "stat_accumulator bulk: %d batters, %d pitchers, %d fielders, "
        "%d game batting lines, %d game pitching lines, %d substitutions%s",
        totals["batters"], totals["pitchers"], totals["fielders"],
        len(game_batting_params), len(game_pitching_params),
        len(substitution_params),
        " (resim mode)" if is_resim else "",
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
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        total = _chunked_execute(conn, _USAGE_UPSERT, usage_params)
        logger.info("stat_accumulator bulk: %d position usage rows upserted", total)
        return total
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
    finally:
        try:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        except Exception:
            pass
