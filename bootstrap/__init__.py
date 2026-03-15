# bootstrap/__init__.py
import logging
import time
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select, and_, text, func, literal
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

bootstrap_bp = Blueprint("bootstrap", __name__)
log = logging.getLogger("app")

# Minimum thresholds for stat leaders
MIN_AT_BATS = 20
MIN_IP_OUTS = 30       # ~10 innings
MIN_FIELDING_GAMES = 5

# Level IDs: 1=hs, 2=intam, 3=college, 4=scraps, 5=a, 6=higha, 7=aa, 8=aaa, 9=mlb
LEVEL_MAP = {
    9: "mlb", 8: "aaa", 7: "aa", 6: "higha", 5: "a", 4: "scraps",
    3: "college", 2: "intam", 1: "hs",
}


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
            "org_ledger":          Table("org_ledger_entries", md, autoload_with=engine),
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
            special_events = _get_special_events(conn, ctx)

            # Financials — graceful fallback if ledger table is empty/missing
            financials = None
            try:
                financials = _get_financials(conn, tables, org_id, ctx)
            except Exception:
                log.debug("bootstrap: financials unavailable, skipping")

            # Listed positions — attach to each player in RosterMap
            try:
                from services.listed_position import get_listed_positions_for_teams
                lyid = ctx["current_league_year_id"]
                team_ids_for_pos = list(roster_map.keys())
                pos_by_team = get_listed_positions_for_teams(conn, team_ids_for_pos, lyid)
                for tid, players in roster_map.items():
                    pos_map = pos_by_team.get(tid, {})
                    for p in players:
                        p["listed_position"] = pos_map.get(p["id"])
            except Exception:
                log.debug("bootstrap: listed positions unavailable, skipping")

            # Face data — deterministic player portraits for facesjs
            face_data = {}
            try:
                from services.face_generator import generate_faces_for_roster, load_face_config
                face_config = load_face_config(conn)
                face_data = generate_faces_for_roster(roster_map, config=face_config)
            except Exception:
                log.debug("bootstrap: face generation unavailable, skipping")

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
            "Financials":    financials,
            "FaceData":      face_data,
            "SpecialEvents": special_events,
        }), 200

    except SQLAlchemyError:
        log.exception("bootstrap landing: db error")
        return jsonify(error="db_unavailable",
                       message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# GET /api/v1/bootstrap/landing/all
# ---------------------------------------------------------------------------
@bootstrap_bp.get("/bootstrap/landing/all")
def get_landing_all():
    """
    All-orgs bootstrap. Returns shared data at the top level and per-org
    data keyed by org_id inside an ``Orgs`` map.

    Shared (queried once):
        SeasonContext, Standings, AllTeams, AllGames, FaceData

    Per-org:
        Organization, RosterMap, Notifications, News,
        TopBatter, TopPitcher, TopFielder, InjuryReport, Financials
    """
    engine = get_engine()
    tables = _get_tables()

    try:
        with engine.connect() as conn:
            # ── Shared data ──────────────────────────────────────
            ctx = _resolve_season_context(conn, tables)
            if ctx is None:
                return jsonify(error="no_league_state",
                               message="League state not initialized"), 404

            standings = _get_standings(conn, tables, ctx)
            all_teams = _get_all_teams(conn, tables)
            all_games = _get_all_games_unfiltered(conn, tables, ctx)
            special_events = _get_special_events(conn, ctx)

            # ── Enumerate orgs ───────────────────────────────────
            orgs_table = tables["organizations"]
            org_rows = conn.execute(
                select(orgs_table.c.id).where(orgs_table.c.id < 31)
            ).all()
            org_ids = [r[0] for r in org_rows]

            # Face config loaded once, reused for all orgs
            face_config = None
            try:
                from services.face_generator import load_face_config
                face_config = load_face_config(conn)
            except Exception:
                log.debug("bootstrap/all: face config unavailable")

            # ── Batch-load per-org data (replaces N+1 loop) ──────
            batch_orgs = _get_all_organizations(conn, tables, org_ids)
            batch_rosters = _get_all_rosters(conn, tables, org_ids)

            # Build flat list of all team_ids across orgs for notification/news queries
            all_team_ids_flat = []
            org_team_map = {}  # {org_id: [team_ids]}
            for oid in org_ids:
                org = batch_orgs.get(oid)
                if org is None:
                    continue
                tids = _get_org_team_ids(org)
                org_team_map[oid] = tids
                all_team_ids_flat.extend(tids)

            batch_notifs = _get_all_notifications(conn, tables, all_team_ids_flat)
            batch_news = _get_all_news(conn, tables, all_team_ids_flat)
            batch_injuries = _get_all_injury_reports(conn, tables, org_ids)

            # Listed positions — single batch call for all teams
            pos_by_team = {}
            try:
                from services.listed_position import get_listed_positions_for_teams
                lyid = ctx["current_league_year_id"]
                pos_by_team = get_listed_positions_for_teams(conn, all_team_ids_flat, lyid)
            except Exception:
                pass

            # Visibility context for all orgs' rosters
            for oid in org_ids:
                roster_map = batch_rosters.get(oid, {})
                if roster_map:
                    _attach_visibility_context(conn, oid, roster_map)

            # ── Assemble per-org output ──────────────────────────
            orgs_map = {}
            all_face_data = {}

            for oid in org_ids:
                org = batch_orgs.get(oid)
                if org is None:
                    continue

                team_ids = org_team_map.get(oid, [])
                roster_map = batch_rosters.get(oid, {})

                # Collect notifications/news by team_id
                org_notifs = []
                org_news = []
                for tid in team_ids:
                    org_notifs.extend(batch_notifs.get(tid, []))
                    org_news.extend(batch_news.get(tid, []))

                # Top players — still per-org (complex aggregation with LIMIT)
                top_batter = _get_top_batter(conn, tables, ctx, team_ids)
                top_pitcher = _get_top_pitcher(conn, tables, ctx, team_ids)
                top_fielder = _get_top_fielder(conn, tables, ctx, team_ids)

                injury_report = batch_injuries.get(oid, [])

                financials = None
                try:
                    financials = _get_financials(conn, tables, oid, ctx)
                except Exception:
                    pass

                # Attach listed positions
                for tid, players in roster_map.items():
                    pm = pos_by_team.get(tid, {})
                    for p in players:
                        p["listed_position"] = pm.get(p["id"])

                # Face data per org's roster
                if face_config is not None:
                    try:
                        from services.face_generator import generate_faces_for_roster
                        org_faces = generate_faces_for_roster(roster_map, config=face_config)
                        all_face_data.update(org_faces)
                    except Exception:
                        pass

                orgs_map[str(oid)] = {
                    "Organization":  org,
                    "RosterMap":     roster_map,
                    "Notifications": org_notifs,
                    "News":          org_news,
                    "TopBatter":     top_batter,
                    "TopPitcher":    top_pitcher,
                    "TopFielder":    top_fielder,
                    "InjuryReport":  injury_report,
                    "Financials":    financials,
                }

        return jsonify({
            "SeasonContext":  ctx,
            "Standings":      standings,
            "AllTeams":       all_teams,
            "AllGames":       all_games,
            "FaceData":       all_face_data,
            "SpecialEvents":  special_events,
            "Orgs":           orgs_map,
        }), 200

    except SQLAlchemyError:
        log.exception("bootstrap landing/all: db error")
        return jsonify(error="db_unavailable",
                       message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Season context cache — changes only on admin sim-advance
_ctx_cache = None
_ctx_ts = 0.0
_CTX_TTL = 60  # seconds


def invalidate_season_context():
    """Clear cached season context (call after week/phase changes)."""
    global _ctx_cache, _ctx_ts
    _ctx_cache = None
    _ctx_ts = 0.0


def _resolve_season_context(conn, tables):
    """Derive current league year, season id, and week from league_state."""
    global _ctx_cache, _ctx_ts

    now = time.monotonic()
    if _ctx_cache is not None and (now - _ctx_ts) < _CTX_TTL:
        return dict(_ctx_cache)

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

    result = {
        "current_league_year_id": ls_d["current_league_year_id"],
        "league_year": ly_d["league_year"],
        "current_season_id": season_id,
        "current_week_index": gw_d.get("week_index"),
    }

    _ctx_cache = result
    _ctx_ts = now
    return dict(result)


# ---------------------------------------------------------------------------
# Batch helpers for /landing/all (reduce N+1 queries)
# ---------------------------------------------------------------------------

def _get_all_organizations(conn, tables, org_ids):
    """Fetch all orgs + their teams in 2 queries instead of 2×N."""
    orgs = tables["organizations"]
    teams = tables["teams"]

    org_rows = conn.execute(select(orgs).where(orgs.c.id.in_(org_ids))).all()
    team_rows = conn.execute(select(teams).where(teams.c.orgID.in_(org_ids))).all()

    # Group teams by orgID
    teams_by_org = {}
    for tr in team_rows:
        td = _row_to_dict(tr)
        teams_by_org.setdefault(td["orgID"], []).append(td)

    result = {}
    for org_row in org_rows:
        org_d = _row_to_dict(org_row)
        oid = org_d["id"]

        teams_by_level = {}
        for td in teams_by_org.get(oid, []):
            teams_by_level[td["team_level"]] = td

        shaped_teams = {}
        for level_id, td in teams_by_level.items():
            level_name = LEVEL_MAP.get(level_id, f"level_{level_id}")
            shaped_teams[level_name] = {
                "team_id": td.get("id"),
                "team_abbrev": td.get("team_abbrev"),
                "team_city": td.get("team_city"),
                "team_nickname": td.get("team_nickname"),
                "team_full_name": (
                    f"{td.get('team_name', '')} {td.get('team_nickname', '')}".strip()
                    or None
                ),
                "color_one": td.get("color_one"),
                "color_two": td.get("color_two"),
                "color_three": td.get("color_three"),
                "conference": td.get("conference"),
                "division": td.get("division"),
                "stadium_lat": float(td["stadium_lat"]) if td.get("stadium_lat") is not None else None,
                "stadium_long": float(td["stadium_long"]) if td.get("stadium_long") is not None else None,
            }

        org_out = {
            "id": oid,
            "org_abbrev": org_d.get("org_abbrev"),
            "cash": float(org_d["cash"]) if org_d.get("cash") is not None else None,
            "league": org_d.get("league", "mlb"),
            "teams": shaped_teams,
        }

        league = org_d.get("league", "mlb")
        if league == "mlb":
            org_out["owner_name"] = org_d.get("owner_name", "")
            org_out["gm_name"] = org_d.get("gm_name", "")
            org_out["manager_name"] = org_d.get("manager_name", "")
            org_out["scout_name"] = org_d.get("scout_name", "")
        elif league == "college":
            org_out["coach"] = org_d.get("coach", "AI")

        result[oid] = org_out

    return result


def _get_all_rosters(conn, tables, org_ids):
    """
    Fetch rosters for all orgs in 1 query instead of N.
    Returns {org_id: {team_id: [player_dicts]}}.
    """
    import re
    from rosters import _compute_derived_raw_ratings, _load_position_weights

    c = tables["contracts"]
    cd = tables["contract_details"]
    cts = tables["contract_team_share"]
    p = tables["players"]
    t = tables["teams"]
    lvl = tables["levels"]

    stmt = (
        select(
            p,
            c.c.id.label("contract_id"),
            c.c.years.label("contract_years"),
            c.c.current_year.label("contract_current_year"),
            c.c.leagueYearSigned,
            c.c.isActive.label("contract_isActive"),
            c.c.isBuyout.label("contract_isBuyout"),
            c.c.isExtension.label("contract_isExtension"),
            c.c.isFinished.label("contract_isFinished"),
            c.c.bonus.label("contract_bonus"),
            c.c.current_level,
            c.c.onIR,
            cd.c.id.label("detail_id"),
            cd.c.year.label("year_index"),
            cd.c.salary,
            cts.c.salary_share,
            cts.c.orgID.label("org_id"),
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
        .where(and_(c.c.isActive == 1, cts.c.isHolder == 1, cts.c.orgID.in_(org_ids)))
    )

    rows = conn.execute(stmt).all()
    if not rows:
        return {}

    # Load shared lookups once
    dist_by_level = {}
    try:
        from services.rating_config import get_rating_config_by_level_name
        dist_by_level = get_rating_config_by_level_name(conn) or {}
    except Exception:
        pass

    position_weights = _load_position_weights(conn)

    pitch_comp_re = re.compile(r"^pitch\d+_(pacc|pbrk|pcntrl|consist)_base$")
    col_names = [k for k in rows[0]._mapping.keys()]
    base_cols = [n for n in col_names if n.endswith("_base")]
    pot_cols = [n for n in col_names if n.endswith("_pot")]
    derived_cols = [n for n in col_names
                    if n.endswith("_rating") or re.match(r"^pitch\d+_ovr$", n)]
    bio_skip = set(base_cols + pot_cols + derived_cols +
                   ["team", "current_level", "onIR", "salary",
                    "salary_share", "team_id", "team_abbrev", "league_level",
                    "contract_id", "contract_years", "contract_current_year",
                    "leagueYearSigned", "contract_isActive", "contract_isBuyout",
                    "contract_isExtension", "contract_isFinished", "contract_bonus",
                    "detail_id", "year_index", "org_id"])

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

    # {org_id: {team_id: [player_dicts]}}
    all_rosters = {}
    seen = set()
    for row in rows:
        m = row._mapping
        player_id = m["id"]
        org_id = m["org_id"]
        team_id = m["team_id"]
        if player_id in seen:
            continue
        seen.add(player_id)

        ptype = (m.get("ptype") or "").strip()
        league_level = m.get("league_level")

        ptype_dist = dist_by_level.get(ptype) or dist_by_level.get("all") or {}
        dist_for_level = ptype_dist.get(league_level, {})

        bio = {}
        for k in col_names:
            if k not in bio_skip:
                bio[k] = m.get(k)

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

        raw_derived = _compute_derived_raw_ratings(row, position_weights)
        for attr_name, raw_val in raw_derived.items():
            d = dist_for_level.get(attr_name)
            if d and d.get("mean") is not None:
                ratings[attr_name] = _to_20_80(raw_val, d["mean"], d["std"])
            else:
                ratings[attr_name] = None

        potentials = {}
        for col in pot_cols:
            potentials[col] = m.get(col)

        base_salary = m.get("salary")
        share = m.get("salary_share")
        salary_for_org = None
        if base_salary is not None and share is not None:
            try:
                salary_for_org = float(base_salary) * float(share)
            except (TypeError, ValueError):
                pass

        contract = {
            "id": m.get("contract_id"),
            "years": m.get("contract_years"),
            "current_year": m.get("contract_current_year"),
            "league_year_signed": m.get("leagueYearSigned"),
            "is_active": bool(m.get("contract_isActive") or 0),
            "is_buyout": bool(m.get("contract_isBuyout") or 0),
            "is_extension": bool(m.get("contract_isExtension") or 0),
            "is_finished": bool(m.get("contract_isFinished") or 0),
            "on_ir": bool(m.get("onIR") or 0),
            "bonus": float(m.get("contract_bonus") or 0),
            "current_year_detail": {
                "id": m.get("detail_id"),
                "year_index": m.get("year_index"),
                "base_salary": float(base_salary) if base_salary is not None else None,
                "salary_share": float(share) if share is not None else None,
                "salary_for_org": salary_for_org,
            },
        }

        player = {
            **bio,
            "current_level": m.get("current_level"),
            "league_level": league_level,
            "team_abbrev": m.get("team_abbrev"),
            "contract": contract,
            "ratings": ratings,
            "potentials": potentials,
        }
        all_rosters.setdefault(org_id, {}).setdefault(team_id, []).append(player)

    return all_rosters


def _get_all_notifications(conn, tables, team_ids):
    """Fetch notifications for all teams in 1 query. Returns {team_id: [notif_dicts]}."""
    if not team_ids:
        return {}
    n = tables["notifications"]
    rows = conn.execute(
        select(n).where(n.c.team_id.in_(team_ids)).order_by(n.c.created_at.desc())
    ).all()
    result = {}
    for r in rows:
        d = _row_to_dict(r)
        result.setdefault(d["team_id"], []).append(d)
    return result


def _get_all_news(conn, tables, team_ids):
    """Fetch news for all teams in 1 query. Returns {team_id: [news_dicts]}."""
    if not team_ids:
        return {}
    n = tables["news"]
    rows = conn.execute(
        select(n).where(n.c.team_id.in_(team_ids)).order_by(n.c.created_at.desc())
    ).all()
    result = {}
    for r in rows:
        d = _row_to_dict(r)
        result.setdefault(d["team_id"], []).append(d)
    return result


def _get_all_injury_reports(conn, tables, org_ids):
    """Fetch injury reports for all orgs in 1 query. Returns {org_id: [injury_dicts]}."""
    if not org_ids:
        return {}
    placeholders = ", ".join(f":oid{i}" for i in range(len(org_ids)))
    sql = text(f"""
        SELECT p.id AS player_id, p.firstname, p.lastname, p.ptype AS position,
               it.name AS injury_type, pis.weeks_remaining,
               cts.orgID AS org_id
        FROM player_injury_state pis
        JOIN player_injury_events pie ON pie.id = pis.current_event_id
        JOIN injury_types it ON it.id = pie.injury_type_id
        JOIN simbbPlayers p ON p.id = pis.player_id
        JOIN contracts c ON c.playerID = p.id AND c.isActive = 1
        JOIN contractDetails cd ON cd.contractID = c.id AND cd.year = c.current_year
        JOIN contractTeamShare cts ON cts.contractDetailsID = cd.id
             AND cts.isHolder = 1 AND cts.orgID IN ({placeholders})
        WHERE pis.status = 'injured'
    """)
    params = {f"oid{i}": oid for i, oid in enumerate(org_ids)}
    rows = conn.execute(sql, params).all()
    result = {}
    for r in rows:
        d = _row_to_dict(r)
        oid = d.pop("org_id")
        result.setdefault(oid, []).append(d)
    return result


# ---------------------------------------------------------------------------
# Single-org helpers (used by /landing/<org_id>)
# ---------------------------------------------------------------------------

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

    # Only include levels the org actually has teams for
    shaped_teams = {}
    for level_id, td in teams_by_level.items():
        level_name = LEVEL_MAP.get(level_id, f"level_{level_id}")
        shaped_teams[level_name] = {
            "team_id": td.get("id"),
            "team_abbrev": td.get("team_abbrev"),
            "team_city": td.get("team_city"),
            "team_nickname": td.get("team_nickname"),
            "team_full_name": (
                f"{td.get('team_name', '')} {td.get('team_nickname', '')}".strip()
                or None
            ),
            "color_one": td.get("color_one"),
            "color_two": td.get("color_two"),
            "color_three": td.get("color_three"),
            "conference": td.get("conference"),
            "division": td.get("division"),
            "stadium_lat": float(td["stadium_lat"]) if td.get("stadium_lat") is not None else None,
            "stadium_long": float(td["stadium_long"]) if td.get("stadium_long") is not None else None,
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


def _attach_visibility_context(conn, org_id, roster_map):
    """
    Add a ``visibility_context`` dict to every player in *roster_map* so the
    frontend knows the fuzz/precision state without per-player scouting calls.

    Single bulk query against ``scouting_actions`` — no N+1.
    """
    # Collect every player id across all teams
    all_players = []
    for team_players in roster_map.values():
        all_players.extend(team_players)

    if not all_players:
        return

    player_ids = [p["id"] for p in all_players]

    # Bulk-load unlocked scouting actions for this org + these players
    unlocked_map: dict[int, set[str]] = {}
    if player_ids:
        placeholders = ", ".join(f":pid{i}" for i in range(len(player_ids)))
        params = {"org_id": org_id}
        params.update({f"pid{i}": pid for i, pid in enumerate(player_ids)})
        rows = conn.execute(
            text(
                f"SELECT player_id, action_type FROM scouting_actions "
                f"WHERE org_id = :org_id AND player_id IN ({placeholders})"
            ),
            params,
        ).all()
        for r in rows:
            unlocked_map.setdefault(r[0], set()).add(r[1])

    for p in all_players:
        pid = p["id"]
        level = p.get("current_level")
        unlocked = unlocked_map.get(pid, set())

        # Determine pool from level
        if level == 1:
            pool = "hs"
        elif level in (2, 3):
            pool = "college"
        else:
            pool = "pro"

        # Determine display format and precision flags
        if pool == "pro":
            p["visibility_context"] = {
                "context": "pro_roster",
                "display_format": "20-80",
                "attributes_precise": "pro_attrs_precise" in unlocked,
                "potentials_precise": "pro_potential_precise" in unlocked,
            }
        elif pool == "college":
            p["visibility_context"] = {
                "context": "college_roster",
                "display_format": "letter_grade",
                "attributes_precise": "draft_attrs_precise" in unlocked,
                "potentials_precise": "college_potential_precise" in unlocked,
            }
        else:
            # HS — attributes always hidden
            p["visibility_context"] = {
                "context": "hs_roster",
                "display_format": "hidden",
                "attributes_precise": False,
                "potentials_precise": "recruit_potential_precise" in unlocked,
            }


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

    # Select ALL player columns + full contract / team metadata
    stmt = (
        select(
            p,
            c.c.id.label("contract_id"),
            c.c.years.label("contract_years"),
            c.c.current_year.label("contract_current_year"),
            c.c.leagueYearSigned,
            c.c.isActive.label("contract_isActive"),
            c.c.isBuyout.label("contract_isBuyout"),
            c.c.isExtension.label("contract_isExtension"),
            c.c.isFinished.label("contract_isFinished"),
            c.c.bonus.label("contract_bonus"),
            c.c.current_level,
            c.c.onIR,
            cd.c.id.label("detail_id"),
            cd.c.year.label("year_index"),
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
                    "salary_share", "team_id", "team_abbrev", "league_level",
                    "contract_id", "contract_years", "contract_current_year",
                    "leagueYearSigned", "contract_isActive", "contract_isBuyout",
                    "contract_isExtension", "contract_isFinished", "contract_bonus",
                    "detail_id", "year_index"])

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

        # Contract details
        base_salary = m.get("salary")
        share = m.get("salary_share")
        salary_for_org = None
        if base_salary is not None and share is not None:
            try:
                salary_for_org = float(base_salary) * float(share)
            except (TypeError, ValueError):
                pass

        contract = {
            "id": m.get("contract_id"),
            "years": m.get("contract_years"),
            "current_year": m.get("contract_current_year"),
            "league_year_signed": m.get("leagueYearSigned"),
            "is_active": bool(m.get("contract_isActive") or 0),
            "is_buyout": bool(m.get("contract_isBuyout") or 0),
            "is_extension": bool(m.get("contract_isExtension") or 0),
            "is_finished": bool(m.get("contract_isFinished") or 0),
            "on_ir": bool(m.get("onIR") or 0),
            "bonus": float(m.get("contract_bonus") or 0),
            "current_year_detail": {
                "id": m.get("detail_id"),
                "year_index": m.get("year_index"),
                "base_salary": float(base_salary) if base_salary is not None else None,
                "salary_share": float(share) if share is not None else None,
                "salary_for_org": salary_for_org,
            },
        }

        player = {
            **bio,
            "current_level": m.get("current_level"),
            "league_level": league_level,
            "team_abbrev": m.get("team_abbrev"),
            "contract": contract,
            "ratings": ratings,
            "potentials": potentials,
        }
        roster_map.setdefault(team_id, []).append(player)

    # --- Visibility context: bulk-load scouting unlocks for this org ---
    _attach_visibility_context(conn, org_id, roster_map)

    return roster_map


def _get_financials(conn, tables, org_id, ctx):
    """
    Org financial summary + obligations for the current league year.

    Returns dict with:
      - summary: P&L, weekly cashflow, starting/ending balance
      - obligations: current-year salary + bonus obligations
      - future_obligations: committed salary by future league year
    Returns None if league_year data is unavailable.
    """
    league_year = ctx["league_year"]

    ledger = tables["org_ledger"]
    ly = tables["league_years"]
    gw = tables["game_weeks"]
    contracts = tables["contracts"]
    details = tables["contract_details"]
    shares = tables["contract_team_share"]
    players = tables["players"]

    # Resolve league_year -> league_year_id, weeks_in_season
    ly_row = conn.execute(
        select(ly.c.id, ly.c.weeks_in_season)
        .where(ly.c.league_year == league_year)
        .limit(1)
    ).first()
    if not ly_row:
        return None

    ly_m = ly_row._mapping
    league_year_id = ly_m["id"]
    weeks_in_season = int(ly_m["weeks_in_season"])

    # ---- Financial Summary ----

    # Seed capital from organizations.cash (initial funds before any ledger activity)
    orgs = tables["organizations"]
    seed_capital = float(conn.execute(
        select(func.coalesce(orgs.c.cash, 0))
        .where(orgs.c.id == org_id)
    ).scalar_one())

    # Starting balance: seed capital + all prior-year ledger entries
    starting_balance = seed_capital + float(conn.execute(
        select(func.coalesce(func.sum(ledger.c.amount), 0))
        .select_from(ledger.join(ly, ledger.c.league_year_id == ly.c.id))
        .where(and_(
            ledger.c.org_id == org_id,
            ly.c.league_year < league_year,
        ))
    ).scalar_one())

    # Year-level entries (no game_week_id) — media, bonus, buyout, interest
    year_level_rows = conn.execute(
        select(
            ledger.c.entry_type,
            func.coalesce(func.sum(ledger.c.amount), 0).label("total"),
        )
        .where(and_(
            ledger.c.org_id == org_id,
            ledger.c.league_year_id == league_year_id,
            ledger.c.game_week_id.is_(None),
        ))
        .group_by(ledger.c.entry_type)
    ).all()

    year_level_totals = {
        r._mapping["entry_type"]: float(r._mapping["total"])
        for r in year_level_rows
    }

    year_start_events = {
        k: v for k, v in year_level_totals.items()
        if k in ("media", "bonus", "buyout")
    }
    interest_events = {
        k: v for k, v in year_level_totals.items()
        if k in ("interest_income", "interest_expense")
    }

    year_start_net = sum(year_start_events.values())
    interest_net = sum(interest_events.values())

    season_revenue = 0.0
    season_expenses = 0.0
    for v in year_level_totals.values():
        if v > 0:
            season_revenue += v
        elif v < 0:
            season_expenses += -v

    balance_after_year_start = starting_balance + year_start_net

    # Weekly entries grouped by week_index + entry_type
    weekly_rows = conn.execute(
        select(
            gw.c.week_index,
            ledger.c.entry_type,
            func.coalesce(func.sum(ledger.c.amount), 0).label("total"),
        )
        .select_from(ledger.join(gw, ledger.c.game_week_id == gw.c.id))
        .where(and_(
            ledger.c.org_id == org_id,
            ledger.c.league_year_id == league_year_id,
        ))
        .group_by(gw.c.week_index, ledger.c.entry_type)
    ).all()

    week_type_totals = {}
    for row in weekly_rows:
        m = row._mapping
        week = m["week_index"]
        etype = m["entry_type"]
        total = float(m["total"])
        week_type_totals.setdefault(week, {})[etype] = total
        if total > 0:
            season_revenue += total
        elif total < 0:
            season_expenses += -total

    weeks_summary = []
    cumulative = balance_after_year_start
    for week_index in range(1, weeks_in_season + 1):
        by_type = week_type_totals.get(week_index, {})
        salary_total = by_type.get("salary", 0.0)
        performance_total = by_type.get("performance", 0.0)
        other_types = {
            k: v for k, v in by_type.items()
            if k not in ("salary", "performance")
        }
        other_in = sum(v for v in other_types.values() if v > 0)
        other_out = -sum(v for v in other_types.values() if v < 0)
        week_net = sum(by_type.values())
        cumulative += week_net
        weeks_summary.append({
            "week_index": week_index,
            "salary_out": -salary_total,
            "performance_in": performance_total,
            "other_in": other_in,
            "other_out": other_out,
            "net": week_net,
            "cumulative_balance": cumulative,
            "by_type": by_type,
        })

    ending_balance_before_interest = cumulative
    ending_balance = ending_balance_before_interest + interest_net

    # ---- Current-Year Obligations ----

    league_year_expr = contracts.c.leagueYearSigned + (details.c.year - literal(1))

    salary_stmt = (
        select(
            contracts.c.id.label("contract_id"),
            contracts.c.leagueYearSigned,
            contracts.c.isActive,
            contracts.c.isBuyout,
            contracts.c.bonus,
            contracts.c.signingOrg,
            details.c.year.label("year_index"),
            details.c.salary,
            shares.c.salary_share,
            shares.c.isHolder,
            players.c.id.label("player_id"),
            players.c.firstname,
            players.c.lastname,
        )
        .select_from(
            contracts.join(details, details.c.contractID == contracts.c.id)
            .join(shares, shares.c.contractDetailsID == details.c.id)
            .join(players, players.c.id == contracts.c.playerID)
        )
        .where(and_(
            league_year_expr == league_year,
            shares.c.orgID == org_id,
            shares.c.salary_share > 0,
        ))
    )
    salary_rows = conn.execute(salary_stmt).all()

    bonus_stmt = (
        select(
            contracts.c.id.label("contract_id"),
            contracts.c.leagueYearSigned,
            contracts.c.isActive,
            contracts.c.isBuyout,
            contracts.c.bonus,
            players.c.id.label("player_id"),
            players.c.firstname,
            players.c.lastname,
        )
        .select_from(contracts.join(players, players.c.id == contracts.c.playerID))
        .where(and_(
            contracts.c.leagueYearSigned == league_year,
            contracts.c.signingOrg == org_id,
            contracts.c.bonus > 0,
        ))
    )
    bonus_rows = conn.execute(bonus_stmt).all()

    def _num(val):
        return float(val) if val is not None else 0.0

    obligations = []
    ob_totals = {
        "active_salary": 0.0,
        "inactive_salary": 0.0,
        "buyout": 0.0,
        "signing_bonus": 0.0,
        "overall": 0.0,
    }

    for row in salary_rows:
        m = row._mapping
        salary = _num(m["salary"])
        share = _num(m["salary_share"])
        base_amount = salary * share
        is_buyout = bool(m.get("isBuyout") or False)
        is_active = bool(m.get("isActive") or False)
        is_holder = bool(m.get("isHolder") or False)

        if is_buyout:
            category = "buyout"
        elif is_active and is_holder:
            category = "active_salary"
        else:
            category = "inactive_salary"

        obligations.append({
            "type": "salary",
            "category": category,
            "player": {
                "id": m["player_id"],
                "firstname": m["firstname"],
                "lastname": m["lastname"],
            },
            "contract_id": m["contract_id"],
            "year_index": m["year_index"],
            "salary": salary,
            "salary_share": share,
            "amount": base_amount,
        })
        ob_totals["overall"] += base_amount
        ob_totals[category] += base_amount

    for row in bonus_rows:
        m = row._mapping
        bonus = _num(m["bonus"])
        if bonus <= 0:
            continue
        is_buyout = bool(m.get("isBuyout") or False)
        category = "buyout" if is_buyout else "signing_bonus"

        obligations.append({
            "type": "bonus",
            "category": category,
            "player": {
                "id": m["player_id"],
                "firstname": m["firstname"],
                "lastname": m["lastname"],
            },
            "contract_id": m["contract_id"],
            "amount": bonus,
        })
        ob_totals["overall"] += bonus
        ob_totals[category] += bonus

    # ---- Future Year Obligations ----

    future_stmt = (
        select(
            (contracts.c.leagueYearSigned + (details.c.year - literal(1))).label("future_year"),
            func.sum(details.c.salary * shares.c.salary_share).label("total_salary"),
        )
        .select_from(
            contracts.join(details, details.c.contractID == contracts.c.id)
            .join(shares, shares.c.contractDetailsID == details.c.id)
        )
        .where(and_(
            (contracts.c.leagueYearSigned + (details.c.year - literal(1))) > league_year,
            shares.c.orgID == org_id,
            shares.c.salary_share > 0,
        ))
        .group_by(text("future_year"))
        .order_by(text("future_year"))
    )
    future_rows = conn.execute(future_stmt).all()
    future_obligations = {
        int(r._mapping["future_year"]): float(r._mapping["total_salary"] or 0)
        for r in future_rows
    }

    return {
        "summary": {
            "starting_balance": starting_balance,
            "season_revenue": season_revenue,
            "season_expenses": season_expenses,
            "year_start_events": year_start_events,
            "weeks": weeks_summary,
            "interest_events": interest_events,
            "ending_balance_before_interest": ending_balance_before_interest,
            "ending_balance": ending_balance,
        },
        "obligations": {
            "league_year": league_year,
            "totals": ob_totals,
            "items": obligations,
        },
        "future_obligations": future_obligations,
    }


def _get_standings(conn, tables, ctx):
    """
    Standings for all teams from game_results.

    Pro teams (level >= 4): grouped by team_level, games_back within level.
    College teams (level 3): grouped by conference, games_back within conference.
      College standings include conference record (conf_wins/conf_losses)
      derived from is_conference flag on gamelist. Conference games_back is
      computed from conference record.
    """
    season_id = ctx.get("current_season_id")
    if season_id is None:
        return []

    # Check if is_conference column exists (migration 018)
    has_conf_col = False
    try:
        conn.execute(text("SELECT is_conference FROM gamelist LIMIT 0"))
        has_conf_col = True
    except Exception:
        pass

    if has_conf_col:
        sql = text("""
            SELECT
                t.id         AS team_id,
                t.team_abbrev,
                t.orgID      AS org_id,
                t.team_level,
                t.conference,
                t.division,
                COALESCE(w.wins, 0)       AS wins,
                COALESCE(l.losses, 0)     AS losses,
                COALESCE(cw.conf_wins, 0)   AS conf_wins,
                COALESCE(cl.conf_losses, 0) AS conf_losses
            FROM teams t
            LEFT JOIN (
                SELECT winning_team_id, COUNT(*) AS wins
                FROM game_results WHERE season = :season_id AND game_type = 'regular'
                GROUP BY winning_team_id
            ) w ON w.winning_team_id = t.id
            LEFT JOIN (
                SELECT losing_team_id, COUNT(*) AS losses
                FROM game_results WHERE season = :season_id AND game_type = 'regular'
                GROUP BY losing_team_id
            ) l ON l.losing_team_id = t.id
            LEFT JOIN (
                SELECT gr.winning_team_id, COUNT(*) AS conf_wins
                FROM game_results gr
                JOIN gamelist gl ON gl.id = gr.game_id
                WHERE gr.season = :season_id AND gr.game_type = 'regular' AND gl.is_conference = 1
                GROUP BY gr.winning_team_id
            ) cw ON cw.winning_team_id = t.id
            LEFT JOIN (
                SELECT gr.losing_team_id, COUNT(*) AS conf_losses
                FROM game_results gr
                JOIN gamelist gl ON gl.id = gr.game_id
                WHERE gr.season = :season_id AND gr.game_type = 'regular' AND gl.is_conference = 1
                GROUP BY gr.losing_team_id
            ) cl ON cl.losing_team_id = t.id
            WHERE t.team_level >= 3
        """)
    else:
        sql = text("""
            SELECT
                t.id         AS team_id,
                t.team_abbrev,
                t.orgID      AS org_id,
                t.team_level,
                t.conference,
                t.division,
                COALESCE(w.wins, 0)   AS wins,
                COALESCE(l.losses, 0) AS losses,
                0 AS conf_wins,
                0 AS conf_losses
            FROM teams t
            LEFT JOIN (
                SELECT winning_team_id, COUNT(*) AS wins
                FROM game_results WHERE season = :season_id AND game_type = 'regular'
                GROUP BY winning_team_id
            ) w ON w.winning_team_id = t.id
            LEFT JOIN (
                SELECT losing_team_id, COUNT(*) AS losses
                FROM game_results WHERE season = :season_id AND game_type = 'regular'
                GROUP BY losing_team_id
            ) l ON l.losing_team_id = t.id
            WHERE t.team_level >= 3
        """)

    rows = conn.execute(sql, {"season_id": season_id}).all()
    standings = [_row_to_dict(r) for r in rows]

    # Compute win_pct and games_back
    # College (level 3): group by conference, rank by conf_win_pct
    # Pro (level >= 4): group by team_level
    groups = {}
    for s in standings:
        total = s["wins"] + s["losses"]
        s["win_pct"] = round(s["wins"] / total, 3) if total > 0 else 0.0

        conf_total = s["conf_wins"] + s["conf_losses"]
        s["conf_win_pct"] = round(s["conf_wins"] / conf_total, 3) if conf_total > 0 else 0.0

        if s["team_level"] == 3:
            conf = s.get("conference") or "Unknown"
            group_key = f"college_{conf}"
        else:
            group_key = s["team_level"]

        groups.setdefault(group_key, []).append(s)

    for group_key, teams in groups.items():
        is_college = str(group_key).startswith("college_")

        if is_college:
            # College: sort and compute GB by conference record
            teams.sort(key=lambda x: x["conf_win_pct"], reverse=True)
            if teams:
                leader_cw = teams[0]["conf_wins"]
                leader_cl = teams[0]["conf_losses"]
                for t in teams:
                    t["games_back"] = (
                        (leader_cw - t["conf_wins"]) + (t["conf_losses"] - leader_cl)
                    ) / 2.0
        else:
            # Pro: sort and compute GB by overall record
            teams.sort(key=lambda x: x["win_pct"], reverse=True)
            if teams:
                leader_w = teams[0]["wins"]
                leader_l = teams[0]["losses"]
                for t in teams:
                    t["games_back"] = (
                        (leader_w - t["wins"]) + (t["losses"] - leader_l)
                    ) / 2.0

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
            gl.game_type,
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


def _get_all_games_unfiltered(conn, tables, ctx):
    """Full season schedule for ALL teams (used by /all endpoint)."""
    season_id = ctx.get("current_season_id")
    if season_id is None:
        return []

    sql = text("""
        SELECT
            gl.id,
            gl.home_team  AS home_team_id,
            gl.away_team  AS away_team_id,
            gl.season_week AS week,
            gl.season_subweek AS game_day,
            gl.game_type,
            gr.home_score,
            gr.away_score,
            gr.game_outcome,
            CASE WHEN gr.game_id IS NOT NULL THEN 1 ELSE 0 END AS is_complete
        FROM gamelist gl
        LEFT JOIN game_results gr ON gr.game_id = gl.id
        WHERE gl.season = :season_id
        ORDER BY gl.season_week, gl.season_subweek
    """)

    rows = conn.execute(sql, {"season_id": season_id}).all()
    return [_row_to_dict(r) for r in rows]


def _get_special_events(conn, ctx):
    """
    Return active special events (WBC, All-Star, Playoffs) for the current
    league year so the frontend can render them.
    """
    league_year_id = ctx.get("league_year_id")
    if not league_year_id:
        return []

    events = []

    # WBC and All-Star events from special_events table
    try:
        se_rows = conn.execute(text("""
            SELECT id, league_year_id, event_type, status,
                   created_at, completed_at, metadata_json
            FROM special_events
            WHERE league_year_id = :lyid
            ORDER BY created_at DESC
        """), {"lyid": league_year_id}).mappings().all()

        for r in se_rows:
            evt = {
                "id": int(r["id"]),
                "league_year_id": int(r["league_year_id"]),
                "event_type": r["event_type"],
                "status": r["status"],
                "created_at": str(r["created_at"]) if r["created_at"] else None,
                "completed_at": str(r["completed_at"]) if r["completed_at"] else None,
            }

            # For WBC events, include teams and pool standings
            if r["event_type"] == "wbc":
                wbc_rows = conn.execute(text("""
                    SELECT country_name, country_code, pool_group,
                           pool_wins, pool_losses, eliminated, seed
                    FROM wbc_teams WHERE event_id = :eid
                    ORDER BY pool_group, pool_wins DESC, pool_losses ASC
                """), {"eid": int(r["id"])}).mappings().all()
                evt["teams"] = [{
                    "country_name": w["country_name"],
                    "country_code": w["country_code"],
                    "pool_group": w["pool_group"],
                    "pool_wins": int(w["pool_wins"]),
                    "pool_losses": int(w["pool_losses"]),
                    "eliminated": bool(w["eliminated"]),
                    "seed": int(w["seed"]) if w["seed"] else None,
                } for w in wbc_rows]

                # Include WBC games
                import json
                meta = json.loads(r["metadata_json"] or "{}")
                team_map = meta.get("team_map", {})
                team_ids = list(team_map.values())
                if team_ids:
                    placeholders = ",".join(str(tid) for tid in team_ids)
                    wbc_games = conn.execute(text(f"""
                        SELECT gl.id, gl.home_team AS home_team_id,
                               gl.away_team AS away_team_id,
                               gl.season_week AS week,
                               gl.season_subweek AS game_day,
                               gl.game_type,
                               gr.home_score, gr.away_score, gr.game_outcome,
                               CASE WHEN gr.game_id IS NOT NULL THEN 1 ELSE 0 END AS is_complete
                        FROM gamelist gl
                        LEFT JOIN game_results gr ON gr.game_id = gl.id
                        WHERE gl.game_type = 'wbc'
                          AND (gl.home_team IN ({placeholders})
                               OR gl.away_team IN ({placeholders}))
                        ORDER BY gl.season_week, gl.season_subweek
                    """)).mappings().all()
                    evt["games"] = [dict(g) for g in wbc_games]
                    evt["team_map"] = team_map

            # For All-Star events, include rosters
            if r["event_type"] == "allstar":
                roster_rows = conn.execute(text("""
                    SELECT ser.team_label, ser.player_id, ser.position_code,
                           ser.is_starter, p.firstName, p.lastName
                    FROM special_event_rosters ser
                    JOIN simbbPlayers p ON p.id = ser.player_id
                    WHERE ser.event_id = :eid
                    ORDER BY ser.team_label, ser.is_starter DESC, ser.position_code
                """), {"eid": int(r["id"])}).mappings().all()
                rosters = {}
                for rr in roster_rows:
                    label = rr["team_label"]
                    rosters.setdefault(label, []).append({
                        "player_id": int(rr["player_id"]),
                        "name": f"{rr['firstName']} {rr['lastName']}".strip(),
                        "position": rr["position_code"],
                        "is_starter": bool(rr["is_starter"]),
                    })
                evt["rosters"] = rosters

            events.append(evt)
    except Exception:
        log.debug("bootstrap: special_events table unavailable, skipping")

    # Playoff status from playoff_series table
    try:
        ps_rows = conn.execute(text("""
            SELECT league_level, round, series_number,
                   team_a_id, team_b_id, seed_a, seed_b,
                   wins_a, wins_b, series_length, status,
                   winner_team_id, start_week, conference
            FROM playoff_series
            WHERE league_year_id = :lyid
            ORDER BY league_level DESC, round, series_number
        """), {"lyid": league_year_id}).mappings().all()

        if ps_rows:
            # Group by league_level
            by_level = {}
            for r in ps_rows:
                lvl = int(r["league_level"])
                by_level.setdefault(lvl, []).append({
                    "round": r["round"],
                    "series_number": int(r["series_number"]),
                    "team_a_id": int(r["team_a_id"]),
                    "team_b_id": int(r["team_b_id"]),
                    "seed_a": int(r["seed_a"]) if r["seed_a"] else None,
                    "seed_b": int(r["seed_b"]) if r["seed_b"] else None,
                    "wins_a": int(r["wins_a"]),
                    "wins_b": int(r["wins_b"]),
                    "series_length": int(r["series_length"]),
                    "status": r["status"],
                    "winner_team_id": int(r["winner_team_id"]) if r["winner_team_id"] else None,
                    "start_week": int(r["start_week"]),
                    "conference": r["conference"],
                })

            for lvl, series_list in by_level.items():
                total = len(series_list)
                completed = sum(1 for s in series_list if s["status"] == "complete")
                events.append({
                    "id": None,
                    "league_year_id": league_year_id,
                    "event_type": "playoff",
                    "league_level": lvl,
                    "status": "complete" if total == completed else "in_progress",
                    "series": series_list,
                })
    except Exception:
        log.debug("bootstrap: playoff_series table unavailable, skipping")

    return events


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
            t.c.team_name,
            t.c.team_nickname,
            t.c.orgID.label("org_id"),
            t.c.team_level,
            t.c.color_one,
            t.c.color_two,
            t.c.color_three,
            t.c.conference,
            t.c.division,
            t.c.stadium_lat,
            t.c.stadium_long,
        )
    ).all()

    result = []
    for r in rows:
        d = _row_to_dict(r)
        d.pop("team_city", None)
        name = d.pop("team_name") or ""
        nick = d.pop("team_nickname") or ""
        d["team_full_name"] = f"{name} {nick}".strip() or None
        d["stadium_lat"] = float(d["stadium_lat"]) if d.get("stadium_lat") is not None else None
        d["stadium_long"] = float(d["stadium_long"]) if d.get("stadium_long") is not None else None
        result.append(d)
    return result
