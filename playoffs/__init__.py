# playoffs/__init__.py
from flask import Blueprint, jsonify, request
from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine
from services.playoffs import (
    determine_mlb_playoff_field,
    create_mlb_bracket,
    determine_milb_playoff_field,
    create_milb_bracket,
    determine_cws_field,
    create_cws_bracket,
    determine_conf_tournament_fields,
    create_conf_tournaments,
    advance_conf_tournaments,
    wipe_conf_tournaments,
    update_series_after_game,
    advance_round,
    advance_cws_round,
    get_bracket,
    build_bracket_skeleton,
    get_pending_playoff_games,
    process_completed_playoff_games,
    wipe_playoffs,
)

playoffs_bp = Blueprint("playoffs", __name__)


# ---------------------------------------------------------------------------
# Field-editor helpers (preview + validation of hand-edited seedings)
# ---------------------------------------------------------------------------

def _team_pool(conn, league_year_id, level):
    """
    All teams at a level with regular-season W/L for the editor's swap
    dropdowns and record columns.
    """
    rows = conn.execute(sa_text("""
        SELECT t.id, t.team_abbrev, t.conference,
               COALESCE(w.wins, 0) AS wins,
               COALESCE(l.losses, 0) AS losses
        FROM teams t
        LEFT JOIN (
            SELECT winning_team_id, COUNT(*) AS wins
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid LIMIT 1
            ) AND game_type = 'regular'
            GROUP BY winning_team_id
        ) w ON w.winning_team_id = t.id
        LEFT JOIN (
            SELECT losing_team_id, COUNT(*) AS losses
            FROM game_results
            WHERE season = (
                SELECT s.id FROM seasons s
                JOIN league_years ly ON ly.league_year = s.year
                WHERE ly.id = :lyid LIMIT 1
            ) AND game_type = 'regular'
            GROUP BY losing_team_id
        ) l ON l.losing_team_id = t.id
        WHERE t.team_level = :lvl
        ORDER BY t.conference, t.team_abbrev
    """), {"lyid": league_year_id, "lvl": level}).mappings().all()
    pool = []
    for r in rows:
        wins, losses = int(r["wins"]), int(r["losses"])
        total = wins + losses
        pool.append({
            "team_id": int(r["id"]),
            "team_abbrev": r["team_abbrev"],
            "conference": r["conference"],
            "wins": wins,
            "losses": losses,
            "win_pct": round(wins / total, 3) if total else 0.0,
        })
    return pool


def _check_seeds(teams, size):
    """Seeds must be exactly 1..size with no duplicate seeds or teams."""
    seeds = sorted(int(t["seed"]) for t in teams)
    if seeds != list(range(1, size + 1)):
        raise ValueError(f"Seeds must be exactly 1..{size} with no gaps or duplicates")
    tids = [int(t["team_id"]) for t in teams]
    if len(set(tids)) != len(tids):
        raise ValueError("The same team appears more than once")


def _verify_teams(conn, team_ids, level, conference=None):
    """Confirm every team exists at the expected level (and conference)."""
    ids = [int(t) for t in team_ids]
    if not ids:
        raise ValueError("Field is empty")
    csv = ",".join(str(i) for i in ids)
    rows = conn.execute(sa_text(
        f"SELECT id, team_level, conference FROM teams WHERE id IN ({csv})"
    )).mappings().all()
    found = {int(r["id"]): r for r in rows}
    for tid in ids:
        if tid not in found:
            raise ValueError(f"Team {tid} does not exist")
        if int(found[tid]["team_level"]) != level:
            raise ValueError(f"Team {tid} is not at level {level}")
        if conference is not None and found[tid]["conference"] != conference:
            raise ValueError(f"Team {tid} is not in conference {conference}")


def _validate_mlb_field(conn, field):
    if not isinstance(field, dict) or not {"AL", "NL"}.issubset(field.keys()):
        raise ValueError("MLB field must contain AL and NL")
    all_ids = []
    for conf in ("AL", "NL"):
        teams = field[conf]
        if len(teams) != 6:
            raise ValueError(f"{conf} must have exactly 6 seeds")
        _check_seeds(teams, 6)
        _verify_teams(conn, [t["team_id"] for t in teams], 9, conf)
        all_ids += [int(t["team_id"]) for t in teams]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("A team appears in both conferences")


def _validate_flat_field(conn, field, size, level):
    if not isinstance(field, list) or len(field) != size:
        raise ValueError(f"Field must contain exactly {size} teams")
    _check_seeds(field, size)
    _verify_teams(conn, [t["team_id"] for t in field], level)


def _validate_conf_fields(conn, fields):
    if not isinstance(fields, dict) or not fields:
        raise ValueError("No conference fields provided")
    for conf, teams in fields.items():
        if len(teams) < 2:
            raise ValueError(f"{conf}: a tournament needs at least 2 teams")
        _check_seeds(teams, len(teams))
        _verify_teams(conn, [t["team_id"] for t in teams], 3, conf)


@playoffs_bp.get("/special-events")
def list_special_events():
    """
    List all special events, optionally filtered by league_year_id and/or type.
    Also returns playoff status per league level.

    Query params:
      league_year_id (optional) — filter to a specific league year
      event_type     (optional) — "allstar", "wbc", or "playoff"
    """
    league_year_id = request.args.get("league_year_id", type=int)
    event_type = request.args.get("event_type")

    engine = get_engine()
    try:
        with engine.connect() as conn:
            events = []

            # Special events (allstar, wbc)
            if event_type in (None, "allstar", "wbc"):
                conditions = []
                params = {}
                if league_year_id is not None:
                    conditions.append("league_year_id = :lyid")
                    params["lyid"] = league_year_id
                if event_type is not None and event_type != "playoff":
                    conditions.append("event_type = :etype")
                    params["etype"] = event_type

                where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
                rows = conn.execute(sa_text(f"""
                    SELECT id, league_year_id, event_type, status,
                           created_at, completed_at
                    FROM special_events
                    {where}
                    ORDER BY created_at DESC
                """), params).mappings().all()

                for r in rows:
                    events.append({
                        "id": int(r["id"]),
                        "league_year_id": int(r["league_year_id"]),
                        "event_type": r["event_type"],
                        "status": r["status"],
                        "created_at": str(r["created_at"]) if r["created_at"] else None,
                        "completed_at": str(r["completed_at"]) if r["completed_at"] else None,
                    })

            # Playoff status per level (derived from playoff_series)
            if event_type in (None, "playoff"):
                ps_conditions = []
                ps_params = {}
                if league_year_id is not None:
                    ps_conditions.append("league_year_id = :lyid")
                    ps_params["lyid"] = league_year_id

                ps_where = ("WHERE " + " AND ".join(ps_conditions)) if ps_conditions else ""
                ps_rows = conn.execute(sa_text(f"""
                    SELECT league_year_id, league_level,
                           COUNT(*) AS total_series,
                           SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS completed,
                           MAX(round) AS latest_round,
                           MAX(CASE WHEN winner_team_id IS NOT NULL THEN 1 ELSE 0 END) AS has_winner
                    FROM playoff_series
                    {ps_where}
                    GROUP BY league_year_id, league_level
                    ORDER BY league_year_id DESC, league_level DESC
                """), ps_params).mappings().all()

                for r in ps_rows:
                    total = int(r["total_series"])
                    completed = int(r["completed"])
                    events.append({
                        "id": None,
                        "league_year_id": int(r["league_year_id"]),
                        "event_type": "playoff",
                        "league_level": int(r["league_level"]),
                        "status": "complete" if total == completed else "in_progress",
                        "total_series": total,
                        "completed_series": completed,
                        "latest_round": r["latest_round"],
                        "created_at": None,
                        "completed_at": None,
                    })

        return jsonify(events=events), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/generate")
def generate_playoffs():
    """
    Generate playoff bracket for a given league level.
    Body: {league_year_id, league_level, start_week?}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])
    start_week = int(data.get("start_week", 53 if league_level == 9 else 40))
    # Optional hand-edited seeding from the admin field editor.  When omitted,
    # the field is computed from records.
    override = data.get("field")

    engine = get_engine()
    try:
        with engine.begin() as conn:
            if league_level == 9:
                if override is not None:
                    _validate_mlb_field(conn, override)
                    field = override
                else:
                    field = determine_mlb_playoff_field(conn, league_year_id)
                result = create_mlb_bracket(conn, league_year_id, field, start_week)
                result["field"] = field
            elif league_level == 3:
                if override is not None:
                    _validate_flat_field(conn, override, 8, 3)
                    field = override
                else:
                    field = determine_cws_field(conn, league_year_id)
                result = create_cws_bracket(conn, league_year_id, field, start_week)
                result["field"] = field
            elif 5 <= league_level <= 8:
                if override is not None:
                    _validate_flat_field(conn, override, 8, league_level)
                    field = override
                else:
                    field = determine_milb_playoff_field(conn, league_year_id, league_level)
                result = create_milb_bracket(
                    conn, league_year_id, league_level, field, start_week
                )
                result["field"] = field
            else:
                return jsonify(error="invalid_level",
                               message=f"Level {league_level} has no playoff format"), 400

        return jsonify(result), 201
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/bracket/<int:league_year_id>/<int:league_level>")
def get_bracket_endpoint(league_year_id: int, league_level: int):
    """Get full bracket state."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = get_bracket(conn, league_year_id, league_level)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/bracket-skeleton/<int:league_year_id>/<int:league_level>")
def get_bracket_skeleton_endpoint(league_year_id: int, league_level: int):
    """
    Full bracket skeleton (every round through the final, with TBD placeholder
    slots for unplayed rounds) for graphic rendering.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = build_bracket_skeleton(conn, league_year_id, league_level)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/field/<int:league_year_id>/<int:league_level>")
def preview_field(league_year_id: int, league_level: int):
    """
    Compute the seeded playoff field WITHOUT creating anything, for the admin
    seeding editor.  Returns the field plus a swap pool of eligible teams.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            if league_level == 9:
                field = determine_mlb_playoff_field(conn, league_year_id)
                return jsonify(format="mlb", field=field,
                               pool=_team_pool(conn, league_year_id, 9)), 200
            elif league_level == 3:
                field = determine_cws_field(conn, league_year_id)
                return jsonify(format="cws", field=field,
                               pool=_team_pool(conn, league_year_id, 3)), 200
            elif 5 <= league_level <= 8:
                field = determine_milb_playoff_field(conn, league_year_id, league_level)
                return jsonify(format="milb", field=field,
                               pool=_team_pool(conn, league_year_id, league_level)), 200
            return jsonify(error="invalid_level",
                           message=f"Level {league_level} has no playoff format"), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/conf-tournaments/field/<int:league_year_id>")
def preview_conf_fields(league_year_id: int):
    """Compute per-conference tournament seedings without creating them."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            fields = determine_conf_tournament_fields(conn, league_year_id)
        return jsonify(format="conf", fields=fields), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/advance")
def advance_playoffs():
    """
    Advance to next round after current round completes.
    Body: {league_year_id, league_level}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            if league_level == 3:
                result = advance_cws_round(conn, league_year_id)
            else:
                result = advance_round(conn, league_year_id, league_level)

        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/update-series")
def update_series():
    """
    Update a series after a game completes.
    Body: {game_id}
    """
    data = request.get_json(force=True)
    game_id = int(data["game_id"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = update_series_after_game(conn, game_id)
        if result is None:
            return jsonify(message="Not a playoff game"), 200
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/pending-games/<int:league_year_id>/<int:league_level>")
def pending_games(league_year_id: int, league_level: int):
    """
    Get all pending (unsimulated) playoff gamelist entries for active/pending series.
    Useful for the admin UI to show which games are next.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            games = get_pending_playoff_games(conn, league_year_id, league_level)
        return jsonify(games=games), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/process-results")
def process_results():
    """
    Scan for completed playoff games that haven't been tracked in playoff_series
    yet and process them. This is a catch-up mechanism for games simulated via
    the normal simulate-week flow.

    Body: {league_year_id, league_level}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            updates = process_completed_playoff_games(
                conn, league_year_id, league_level
            )
        return jsonify(updates=updates, processed=len(updates)), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/process-and-advance")
def process_and_advance():
    """
    One-click cadence helper: process any completed-but-untracked games, then
    advance the bracket.  For College (level 3) it advances BOTH the conference
    tournaments and the CWS (each is a no-op if that sub-tournament isn't ready
    or doesn't exist).

    Body: {league_year_id, league_level}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            processed = process_completed_playoff_games(conn, league_year_id, league_level)
            if league_level == 3:
                advanced = {
                    "conf": advance_conf_tournaments(conn, league_year_id),
                    "cws": advance_cws_round(conn, league_year_id),
                }
            else:
                advanced = advance_round(conn, league_year_id, league_level)
        return jsonify(processed=len(processed), advanced=advanced), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/status/<int:league_year_id>/<int:league_level>")
def playoff_status(league_year_id: int, league_level: int):
    """
    Concise next-action hint for the admin banner: how many games are waiting
    to be simulated, whether a round is complete and ready to advance, or
    whether the bracket is finished.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            counts = conn.execute(sa_text("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS complete
                FROM playoff_series
                WHERE league_year_id = :lyid AND league_level = :level
            """), {"lyid": league_year_id, "level": league_level}).mappings().first()
            total = int(counts["total"] or 0)
            complete = int(counts["complete"] or 0)
            pending = len(get_pending_playoff_games(conn, league_year_id, league_level))

        if total == 0:
            action, message = "none", "No bracket generated yet."
        elif pending > 0:
            action = "simulate"
            message = f"{pending} game(s) pending simulation."
        elif complete < total:
            action = "advance"
            message = "Round complete — ready to Advance."
        else:
            action, message = "complete", "Bracket complete."

        return jsonify(
            league_level=league_level, has_bracket=total > 0,
            total_series=total, complete_series=complete,
            pending_games=pending, next_action=action, message=message,
        ), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.get("/playoffs/health/<int:league_year_id>/<int:league_level>")
def playoff_health(league_year_id: int, league_level: int):
    """
    Integrity check for a bracket.  Flags the failure modes that are otherwise
    invisible: a team live in two series at once, self-matchups, a live series
    with no scheduled game (usually an unprocessed result), teams at the wrong
    level, and an unresolved CWS if-necessary final.
    """
    p = {"lyid": league_year_id, "level": league_level}
    engine = get_engine()
    try:
        with engine.connect() as conn:
            issues = []

            dbl = conn.execute(sa_text("""
                SELECT team_id, COUNT(*) AS c FROM (
                    SELECT team_a_id AS team_id FROM playoff_series
                    WHERE league_year_id = :lyid AND league_level = :level
                      AND status IN ('pending', 'active')
                    UNION ALL
                    SELECT team_b_id FROM playoff_series
                    WHERE league_year_id = :lyid AND league_level = :level
                      AND status IN ('pending', 'active')
                ) x GROUP BY team_id HAVING c > 1
            """), p).mappings().all()
            for r in dbl:
                issues.append({"severity": "error",
                               "message": f"Team {int(r['team_id'])} is in {int(r['c'])} live series at once."})

            self_m = conn.execute(sa_text("""
                SELECT id, round FROM playoff_series
                WHERE league_year_id = :lyid AND league_level = :level
                  AND team_a_id = team_b_id
            """), p).mappings().all()
            for r in self_m:
                issues.append({"severity": "error",
                               "message": f"Series {int(r['id'])} ({r['round']}) is a team against itself."})

            stuck = conn.execute(sa_text("""
                SELECT ps.id, ps.round FROM playoff_series ps
                WHERE ps.league_year_id = :lyid AND ps.league_level = :level
                  AND ps.status IN ('pending', 'active')
                  AND NOT EXISTS (
                      SELECT 1 FROM gamelist gl
                      LEFT JOIN game_results gr ON gr.game_id = gl.id
                      WHERE gl.game_type = 'playoff' AND gl.league_level = :level
                        AND gr.game_id IS NULL
                        AND ((gl.home_team = ps.team_a_id AND gl.away_team = ps.team_b_id)
                          OR (gl.home_team = ps.team_b_id AND gl.away_team = ps.team_a_id))
                  )
            """), p).mappings().all()
            for r in stuck:
                issues.append({"severity": "warn",
                               "message": f"Series {int(r['id'])} ({r['round']}) is live but has no scheduled game — run Process Results."})

            wrong = conn.execute(sa_text("""
                SELECT DISTINCT t.id, t.team_abbrev, t.team_level
                FROM playoff_series ps
                JOIN teams t ON t.id = ps.team_a_id OR t.id = ps.team_b_id
                WHERE ps.league_year_id = :lyid AND ps.league_level = :level
                  AND t.team_level <> :level
            """), p).mappings().all()
            for r in wrong:
                issues.append({"severity": "error",
                               "message": f"{r['team_abbrev']} is level {int(r['team_level'])}, not {league_level}."})

            if league_level == 3:
                f2_done = conn.execute(sa_text("""
                    SELECT COUNT(*) FROM playoff_series
                    WHERE league_year_id = :lyid AND league_level = 3
                      AND round = 'CWS_F2' AND status = 'complete'
                """), p).scalar()
                if f2_done:
                    alive = conn.execute(sa_text("""
                        SELECT COUNT(*) FROM cws_bracket
                        WHERE league_year_id = :lyid AND eliminated = 0
                    """), {"lyid": league_year_id}).scalar()
                    if int(alive or 0) > 1:
                        issues.append({"severity": "error",
                                       "message": "CWS final game is played but more than one team is still alive — Advance to crown the champion."})

        return jsonify(ok=len(issues) == 0, issues=issues), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Conference Tournaments
# ---------------------------------------------------------------------------

@playoffs_bp.post("/playoffs/conf-tournaments/generate")
def generate_conf_tournaments():
    """
    Generate single-elimination conference tournament brackets for all
    college conferences.  All teams qualify; top seeds get byes when the
    conference size is not a power of 2.

    Body: {league_year_id, start_week?}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    start_week = int(data.get("start_week", 25))
    override = data.get("fields")  # optional hand-edited per-conference seeding

    engine = get_engine()
    try:
        with engine.begin() as conn:
            if override is not None:
                _validate_conf_fields(conn, override)
            result = create_conf_tournaments(
                conn, league_year_id, start_week, fields=override
            )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/conf-tournaments/advance")
def advance_conf_tournaments_endpoint():
    """
    Advance all conference tournaments that have completed their current
    round.  Merges bye teams for the R1→R2 transition when applicable.

    Body: {league_year_id}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = advance_conf_tournaments(conn, league_year_id)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


@playoffs_bp.post("/playoffs/conf-tournaments/wipe")
def wipe_conf_tournaments_endpoint():
    """
    Wipe all conference tournament data for a league year, leaving CWS
    data intact.

    Body: {league_year_id}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = wipe_conf_tournaments(conn, league_year_id)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Reschedule a pending playoff game
# ---------------------------------------------------------------------------

@playoffs_bp.post("/playoffs/reschedule-game")
def reschedule_game():
    """
    Move a not-yet-played playoff game to a different (week, subweek) slot.

    Refuses games that already have a result, and rejects a slot where either
    team is already booked.  Structure-only — does not touch series state.

    Body: {game_id, season_week, season_subweek}
    """
    data = request.get_json(force=True)
    game_id = int(data["game_id"])
    week = int(data["season_week"])
    subweek = str(data["season_subweek"]).strip().lower()

    if subweek not in ("a", "b", "c", "d"):
        return jsonify(error="bad_subweek", message="Subweek must be a, b, c, or d"), 400
    if week < 1:
        return jsonify(error="bad_week", message="Week must be positive"), 400

    engine = get_engine()
    try:
        with engine.begin() as conn:
            game = conn.execute(sa_text("""
                SELECT id, home_team, away_team, league_level, game_type
                FROM gamelist WHERE id = :gid
            """), {"gid": game_id}).mappings().first()
            if not game:
                return jsonify(error="not_found", message="Game not found"), 404
            if game["game_type"] != "playoff":
                return jsonify(error="not_playoff",
                               message="Only playoff games can be rescheduled here"), 400

            played = conn.execute(sa_text(
                "SELECT 1 FROM game_results WHERE game_id = :gid"
            ), {"gid": game_id}).first()
            if played:
                return jsonify(error="already_played",
                               message="Cannot reschedule a game that already has a result"), 400

            clash = conn.execute(sa_text("""
                SELECT id FROM gamelist
                WHERE game_type = 'playoff' AND league_level = :lvl
                  AND season_week = :wk AND season_subweek = :sub
                  AND id <> :gid
                  AND (home_team IN (:h, :a) OR away_team IN (:h, :a))
            """), {
                "lvl": int(game["league_level"]), "wk": week, "sub": subweek,
                "gid": game_id, "h": int(game["home_team"]), "a": int(game["away_team"]),
            }).first()
            if clash:
                return jsonify(error="slot_taken",
                               message="One of these teams already has a game in that slot"), 409

            conn.execute(sa_text("""
                UPDATE gamelist SET season_week = :wk, season_subweek = :sub
                WHERE id = :gid
            """), {"wk": week, "sub": subweek, "gid": game_id})

        return jsonify(ok=True, game_id=game_id,
                       season_week=week, season_subweek=subweek), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# Wipe
# ---------------------------------------------------------------------------

@playoffs_bp.post("/playoffs/wipe")
def wipe():
    """
    Wipe all playoff data for a given league year and level.
    Removes series, games, results, and per-game stat lines.
    Season-accumulated stats and stamina are left untouched.

    Body: {league_year_id, league_level}
    """
    data = request.get_json(force=True)
    league_year_id = int(data["league_year_id"])
    league_level = int(data["league_level"])

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = wipe_playoffs(conn, league_year_id, league_level)
        return jsonify(result), 200
    except SQLAlchemyError as e:
        return jsonify(error="database_error", message=str(e)), 500
