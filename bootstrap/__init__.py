# bootstrap/__init__.py
import logging
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select, and_, text
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

bootstrap_bp = Blueprint("bootstrap", __name__)
log = logging.getLogger("app")

# Minimum thresholds for stat leaders
MIN_AT_BATS = 20
MIN_IP_OUTS = 30       # ~10 innings
MIN_FIELDING_GAMES = 5

# Level IDs: 4=scraps, 5=a, 6=higha, 7=aa, 8=aaa, 9=mlb
LEVEL_MAP = {9: "mlb", 8: "aaa", 7: "aa", 6: "higha", 5: "a", 4: "scraps"}


# ---------------------------------------------------------------------------
# Table reflection
# ---------------------------------------------------------------------------
def _get_tables():
    if not hasattr(bootstrap_bp, "_tables"):
        engine = get_engine()
        md = MetaData()
        bootstrap_bp._tables = {
            "organizations":       Table("organizations", md, autoload_with=engine),
            "teams":               Table("teams", md, autoload_with=engine),
            "levels":              Table("levels", md, autoload_with=engine),
            "contracts":           Table("contracts", md, autoload_with=engine),
            "contract_details":    Table("contractDetails", md, autoload_with=engine),
            "contract_team_share": Table("contractTeamShare", md, autoload_with=engine),
            "players":             Table("simbbPlayers", md, autoload_with=engine),
            "league_state":        Table("league_state", md, autoload_with=engine),
            "league_years":        Table("league_years", md, autoload_with=engine),
            "game_weeks":          Table("game_weeks", md, autoload_with=engine),
            "seasons":             Table("seasons", md, autoload_with=engine),
            "gamelist":            Table("gamelist", md, autoload_with=engine),
            "game_results":        Table("game_results", md, autoload_with=engine),
            "notifications":       Table("notifications", md, autoload_with=engine),
            "news":                Table("news", md, autoload_with=engine),
            "batting_stats":       Table("player_batting_stats", md, autoload_with=engine),
            "pitching_stats":      Table("player_pitching_stats", md, autoload_with=engine),
            "fielding_stats":      Table("player_fielding_stats", md, autoload_with=engine),
            "injury_state":        Table("player_injury_state", md, autoload_with=engine),
            "injury_events":       Table("player_injury_events", md, autoload_with=engine),
            "injury_types":        Table("injury_types", md, autoload_with=engine),
        }
    return bootstrap_bp._tables


def _row_to_dict(row):
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# GET /api/v1/bootstrap/landing/<int:org_id>
# ---------------------------------------------------------------------------
@bootstrap_bp.get("/bootstrap/landing/<int:org_id>")
def get_landing(org_id: int):
    engine = get_engine()
    tables = _get_tables()

    try:
        with engine.connect() as conn:
            # Step 0: current season context
            ctx = _resolve_season_context(conn, tables)
            if ctx is None:
                return jsonify(error="no_league_state",
                               message="League state not initialized"), 404

            # Step 1: organization
            org = _get_organization(conn, tables, org_id)
            if org is None:
                return jsonify(error="org_not_found",
                               message="Organization not found"), 404

            team_ids = _get_org_team_ids(org)

            # Steps 2-11: assemble all sections
            roster_map    = _get_roster_map(conn, tables, org_id)
            standings     = _get_standings(conn, tables, ctx)
            all_games     = _get_all_games(conn, tables, ctx, team_ids)
            notifications = _get_notifications(conn, tables, team_ids)
            news          = _get_news(conn, tables, team_ids)
            top_batter    = _get_top_batter(conn, tables, ctx, team_ids)
            top_pitcher   = _get_top_pitcher(conn, tables, ctx, team_ids)
            top_fielder   = _get_top_fielder(conn, tables, ctx, team_ids)
            injury_report = _get_injury_report(conn, tables, org_id)
            all_teams     = _get_all_teams(conn, tables)

        return jsonify({
            "Organization":  org,
            "RosterMap":     roster_map,
            "Standings":     standings,
            "AllGames":      all_games,
            "Notifications": notifications,
            "News":          news,
            "TopBatter":     top_batter,
            "TopPitcher":    top_pitcher,
            "TopFielder":    top_fielder,
            "InjuryReport":  injury_report,
            "AllTeams":      all_teams,
            "SeasonContext":  ctx,
        }), 200

    except SQLAlchemyError:
        log.exception("bootstrap landing: db error")
        return jsonify(error="db_unavailable",
                       message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_season_context(conn, tables):
    """Derive current league year, season id, and week from league_state."""
    ls = tables["league_state"]
    ly = tables["league_years"]
    gw = tables["game_weeks"]
    seasons = tables["seasons"]

    row = conn.execute(select(ls).where(ls.c.id == 1)).first()
    if not row:
        return None
    ls_d = _row_to_dict(row)

    ly_row = conn.execute(
        select(ly).where(ly.c.id == ls_d["current_league_year_id"])
    ).first()
    if not ly_row:
        return None
    ly_d = _row_to_dict(ly_row)

    gw_row = conn.execute(
        select(gw).where(gw.c.id == ls_d["current_game_week_id"])
    ).first()
    gw_d = _row_to_dict(gw_row) if gw_row else {}

    season_row = conn.execute(
        select(seasons).where(seasons.c.year == ly_d["league_year"])
    ).first()
    season_id = _row_to_dict(season_row)["id"] if season_row else None

    return {
        "current_league_year_id": ls_d["current_league_year_id"],
        "league_year": ly_d["league_year"],
        "current_season_id": season_id,
        "current_week_index": gw_d.get("week_index"),
    }


def _get_organization(conn, tables, org_id):
    """Get organization with team structure and role fields."""
    orgs = tables["organizations"]
    teams = tables["teams"]

    org_row = conn.execute(select(orgs).where(orgs.c.id == org_id)).first()
    if not org_row:
        return None
    org_d = _row_to_dict(org_row)

    team_rows = conn.execute(
        select(teams).where(teams.c.orgID == org_id)
    ).all()

    teams_by_level = {}
    for tr in team_rows:
        td = _row_to_dict(tr)
        teams_by_level[td["team_level"]] = td

    shaped_teams = {}
    for level_id, level_name in LEVEL_MAP.items():
        t = teams_by_level.get(level_id, {})
        shaped_teams[level_name] = {
            "team_id": t.get("id"),
            "team_abbrev": t.get("team_abbrev"),
            "team_city": t.get("team_city"),
            "team_nickname": t.get("team_nickname"),
            "team_full_name": (
                f"{t.get('team_city', '')} {t.get('team_nickname', '')}".strip()
                if t else None
            ),
        }

    result = {
        "id": org_d["id"],
        "org_abbrev": org_d.get("org_abbrev"),
        "cash": float(org_d["cash"]) if org_d.get("cash") is not None else None,
        "league": org_d.get("league", "mlb"),
        "teams": shaped_teams,
    }

    league = org_d.get("league", "mlb")
    if league == "mlb":
        result["owner_name"] = org_d.get("owner_name", "")
        result["gm_name"] = org_d.get("gm_name", "")
        result["manager_name"] = org_d.get("manager_name", "")
        result["scout_name"] = org_d.get("scout_name", "")
    elif league == "college":
        result["coach"] = org_d.get("coach", "AI")

    return result


def _get_org_team_ids(org):
    """Extract all team_ids from the shaped org dict."""
    ids = []
    for level_data in org.get("teams", {}).values():
        tid = level_data.get("team_id")
        if tid is not None:
            ids.append(tid)
    return ids


def _get_roster_map(conn, tables, org_id):
    """
    Players keyed by team_id, with 20-80 scaled ratings and position ratings.

    Each player object includes:
      - bio fields (firstname, lastname, ptype, age, etc.)
      - contract fields (salary, onIR, current_level)
      - ratings dict: {power_display: 70, c_rating: 65, pitch1_ovr: 72, ...}
      - potentials dict: {power_pot: "B+", ...}
    """
    import re
    from rosters import _compute_derived_raw_ratings, _load_position_weights

    c = tables["contracts"]
    cd = tables["contract_details"]
    cts = tables["contract_team_share"]
    p = tables["players"]
    t = tables["teams"]
    lvl = tables["levels"]

    # Select ALL player columns + contract / team metadata
    stmt = (
        select(
            p,
            c.c.current_level,
            c.c.onIR,
            cd.c.salary,
            cts.c.salary_share,
            t.c.id.label("team_id"),
            t.c.team_abbrev,
            lvl.c.league_level,
        )
        .select_from(
            c.join(cd, and_(cd.c.contractID == c.c.id,
                            cd.c.year == c.c.current_year))
             .join(cts, cts.c.contractDetailsID == cd.c.id)
             .join(p, p.c.id == c.c.playerID)
             .join(t, and_(t.c.orgID == cts.c.orgID,
                           t.c.team_level == c.c.current_level))
             .join(lvl, lvl.c.id == c.c.current_level)
        )
        .where(and_(c.c.isActive == 1, cts.c.isHolder == 1, cts.c.orgID == org_id))
    )

    rows = conn.execute(stmt).all()
    if not rows:
        return {}

    # Load rating distributions and position weights once
    dist_by_level = {}
    try:
        from services.rating_config import get_rating_config_by_level_name
        dist_by_level = get_rating_config_by_level_name(conn) or {}
    except Exception:
        pass

    position_weights = _load_position_weights(conn)

    # Classify player columns from the first row
    pitch_comp_re = re.compile(r"^pitch\d+_(pacc|pbrk|pcntrl|consist)_base$")
    col_names = [k for k in rows[0]._mapping.keys()]
    base_cols = [n for n in col_names if n.endswith("_base")]
    pot_cols = [n for n in col_names if n.endswith("_pot")]
    derived_cols = [n for n in col_names
                    if n.endswith("_rating") or re.match(r"^pitch\d+_ovr$", n)]
    bio_skip = set(base_cols + pot_cols + derived_cols +
                   ["team", "current_level", "onIR", "salary",
                    "salary_share", "team_id", "team_abbrev", "league_level"])

    def _to_20_80(raw_val, mean, std):
        if raw_val is None or mean is None:
            return None
        try:
            x = float(raw_val)
        except (TypeError, ValueError):
            return None
        if std is None or std <= 0:
            z = 0.0
        else:
            z = (x - mean) / std
        z = max(-3.0, min(3.0, z))
        raw_score = 50.0 + (z / 3.0) * 30.0
        score = int(round(max(20.0, min(80.0, raw_score)) / 5.0) * 5)
        return max(20, min(80, score))

    roster_map = {}
    seen = set()
    for row in rows:
        m = row._mapping
        player_id = m["id"]
        team_id = m["team_id"]
        if player_id in seen:
            continue
        seen.add(player_id)

        ptype = (m.get("ptype") or "").strip()
        league_level = m.get("league_level")

        # Distribution lookup: player's ptype → level, fallback to "all"
        ptype_dist = dist_by_level.get(ptype) or dist_by_level.get("all") or {}
        dist_for_level = ptype_dist.get(league_level, {})

        # Bio fields
        bio = {}
        for k in col_names:
            if k not in bio_skip:
                bio[k] = m.get(k)

        # 20-80 ratings for *_base columns
        ratings = {}
        for col in base_cols:
            val = m.get(col)
            mp = pitch_comp_re.match(col)
            dist_key = f"pitch_{mp.group(1)}" if mp else col
            d = dist_for_level.get(dist_key)
            if d and d.get("mean") is not None:
                ratings[col.replace("_base", "_display")] = _to_20_80(val, d["mean"], d["std"])
            else:
                ratings[col.replace("_base", "_display")] = None

        # Derived ratings (position ratings + pitch overalls)
        raw_derived = _compute_derived_raw_ratings(row, position_weights)
        for attr_name, raw_val in raw_derived.items():
            d = dist_for_level.get(attr_name)
            if d and d.get("mean") is not None:
                ratings[attr_name] = _to_20_80(raw_val, d["mean"], d["std"])
            else:
                ratings[attr_name] = None

        # Potentials
        potentials = {}
        for col in pot_cols:
            potentials[col] = m.get(col)

        # Salary
        base_salary = m.get("salary")
        share = m.get("salary_share")
        salary = None
        if base_salary is not None and share is not None:
            try:
                salary = float(base_salary) * float(share)
            except (TypeError, ValueError):
                pass

        player = {
            **bio,
            "current_level": m.get("current_level"),
            "league_level": league_level,
            "team_abbrev": m.get("team_abbrev"),
            "onIR": bool(m.get("onIR") or 0),
            "salary": salary,
            "ratings": ratings,
            "potentials": potentials,
        }
        roster_map.setdefault(team_id, []).append(player)

    return roster_map


def _get_standings(conn, tables, ctx):
    """Standings for all teams at all levels from game_results."""
    season_id = ctx.get("current_season_id")
    if season_id is None:
        return []

    sql = text("""
        SELECT
            t.id         AS team_id,
            t.team_abbrev,
            t.orgID      AS org_id,
            t.team_level,
            COALESCE(w.wins, 0)   AS wins,
            COALESCE(l.losses, 0) AS losses
        FROM teams t
        LEFT JOIN (
            SELECT winning_team_id, COUNT(*) AS wins
            FROM game_results WHERE season = :season_id
            GROUP BY winning_team_id
        ) w ON w.winning_team_id = t.id
        LEFT JOIN (
            SELECT losing_team_id, COUNT(*) AS losses
            FROM game_results WHERE season = :season_id
            GROUP BY losing_team_id
        ) l ON l.losing_team_id = t.id
        WHERE t.team_level >= 4
    """)

    rows = conn.execute(sql, {"season_id": season_id}).all()
    standings = [_row_to_dict(r) for r in rows]

    # Compute win_pct and games_back per level group
    by_level = {}
    for s in standings:
        total = s["wins"] + s["losses"]
        s["win_pct"] = round(s["wins"] / total, 3) if total > 0 else 0.0
        by_level.setdefault(s["team_level"], []).append(s)

    for level, teams in by_level.items():
        teams.sort(key=lambda x: x["win_pct"], reverse=True)
        if teams:
            leader_w = teams[0]["wins"]
            leader_l = teams[0]["losses"]
            for t in teams:
                t["games_back"] = ((leader_w - t["wins"]) + (t["losses"] - leader_l)) / 2.0

    return standings


def _get_all_games(conn, tables, ctx, team_ids):
    """Full season schedule for the org's teams."""
    season_id = ctx.get("current_season_id")
    if not team_ids or season_id is None:
        return []

    placeholders = ", ".join([f":t{i}" for i in range(len(team_ids))])
    params = {f"t{i}": tid for i, tid in enumerate(team_ids)}
    params["season_id"] = season_id

    sql = text(f"""
        SELECT
            gl.id,
            gl.home_team  AS home_team_id,
            gl.away_team  AS away_team_id,
            gl.season_week AS week,
            gl.season_subweek AS game_day,
            gr.home_score,
            gr.away_score,
            gr.game_outcome,
            CASE WHEN gr.game_id IS NOT NULL THEN 1 ELSE 0 END AS is_complete
        FROM gamelist gl
        LEFT JOIN game_results gr ON gr.game_id = gl.id
        WHERE gl.season = :season_id
          AND (gl.home_team IN ({placeholders}) OR gl.away_team IN ({placeholders}))
        ORDER BY gl.season_week, gl.season_subweek
    """)

    rows = conn.execute(sql, params).all()
    return [_row_to_dict(r) for r in rows]


def _get_notifications(conn, tables, team_ids):
    if not team_ids:
        return []
    n = tables["notifications"]
    rows = conn.execute(
        select(n).where(n.c.team_id.in_(team_ids)).order_by(n.c.created_at.desc())
    ).all()
    return [_row_to_dict(r) for r in rows]


def _get_news(conn, tables, team_ids):
    if not team_ids:
        return []
    n = tables["news"]
    rows = conn.execute(
        select(n).where(n.c.team_id.in_(team_ids)).order_by(n.c.created_at.desc())
    ).all()
    return [_row_to_dict(r) for r in rows]


def _get_top_batter(conn, tables, ctx, team_ids):
    """Top batter by batting average (min AB threshold). Returns None if no data."""
    if not team_ids:
        return None
    bs = tables["batting_stats"]
    p = tables["players"]

    avg_expr = (bs.c.hits * 1.0 / bs.c.at_bats)

    stmt = (
        select(
            bs.c.player_id, p.c.firstname, p.c.lastname, p.c.ptype.label("position"),
            bs.c.hits, bs.c.at_bats, bs.c.home_runs.label("hr"), bs.c.rbi,
            avg_expr.label("avg"),
        )
        .select_from(bs.join(p, p.c.id == bs.c.player_id))
        .where(and_(
            bs.c.league_year_id == ctx["current_league_year_id"],
            bs.c.team_id.in_(team_ids),
            bs.c.at_bats >= MIN_AT_BATS,
        ))
        .order_by(avg_expr.desc())
        .limit(1)
    )

    row = conn.execute(stmt).first()
    if not row:
        return None
    d = _row_to_dict(row)
    d["avg"] = round(d["avg"], 3)
    return d


def _get_top_pitcher(conn, tables, ctx, team_ids):
    """Top pitcher by ERA (min IP threshold). Returns None if no data."""
    if not team_ids:
        return None
    ps = tables["pitching_stats"]
    p = tables["players"]

    # ERA = (earned_runs / (innings_pitched_outs / 3)) * 9 = earned_runs * 27 / ipo
    era_expr = (ps.c.earned_runs * 27.0 / ps.c.innings_pitched_outs)

    stmt = (
        select(
            ps.c.player_id, p.c.firstname, p.c.lastname,
            ps.c.wins, ps.c.strikeouts,
            ps.c.innings_pitched_outs,
            era_expr.label("era"),
        )
        .select_from(ps.join(p, p.c.id == ps.c.player_id))
        .where(and_(
            ps.c.league_year_id == ctx["current_league_year_id"],
            ps.c.team_id.in_(team_ids),
            ps.c.innings_pitched_outs >= MIN_IP_OUTS,
        ))
        .order_by(era_expr.asc())
        .limit(1)
    )

    row = conn.execute(stmt).first()
    if not row:
        return None
    d = _row_to_dict(row)
    d["era"] = round(d["era"], 2)
    return d


def _get_top_fielder(conn, tables, ctx, team_ids):
    """Top fielder by fielding percentage (min games threshold). Returns None if no data."""
    if not team_ids:
        return None
    fs = tables["fielding_stats"]
    p = tables["players"]

    total_chances = (fs.c.putouts + fs.c.assists + fs.c.errors)
    fpct_expr = ((fs.c.putouts + fs.c.assists) * 1.0 / total_chances)

    stmt = (
        select(
            fs.c.player_id, p.c.firstname, p.c.lastname,
            fs.c.position_code,
            fpct_expr.label("fielding_pct"),
        )
        .select_from(fs.join(p, p.c.id == fs.c.player_id))
        .where(and_(
            fs.c.league_year_id == ctx["current_league_year_id"],
            fs.c.team_id.in_(team_ids),
            fs.c.games >= MIN_FIELDING_GAMES,
            total_chances > 0,
        ))
        .order_by(fpct_expr.desc())
        .limit(1)
    )

    row = conn.execute(stmt).first()
    if not row:
        return None
    d = _row_to_dict(row)
    d["fielding_pct"] = round(d["fielding_pct"], 3)
    return d


def _get_injury_report(conn, tables, org_id):
    """Injured players on the org's active contracts."""
    sql = text("""
        SELECT p.id AS player_id, p.firstname, p.lastname, p.ptype AS position,
               it.name AS injury_type, pis.weeks_remaining
        FROM player_injury_state pis
        JOIN player_injury_events pie ON pie.id = pis.current_event_id
        JOIN injury_types it ON it.id = pie.injury_type_id
        JOIN simbbPlayers p ON p.id = pis.player_id
        JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
             AND cts.isHolder = 1 AND cts.orgID = :org_id
        WHERE pis.status = 'injured'
    """)

    rows = conn.execute(sql, {"org_id": org_id}).all()
    return [_row_to_dict(r) for r in rows]


def _get_all_teams(conn, tables):
    """Flat team list for schedule display / abbreviation mapping."""
    t = tables["teams"]
    rows = conn.execute(
        select(
            t.c.id.label("team_id"),
            t.c.team_abbrev,
            t.c.team_city,
            t.c.team_nickname,
            t.c.orgID.label("org_id"),
            t.c.team_level,
        )
    ).all()

    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["team_full_name"] = f"{d.pop('team_city')} {d.pop('team_nickname')}".strip()
        result.append(d)
    return result
