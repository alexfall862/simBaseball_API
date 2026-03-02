# orgs/__init__.py
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine


orgs_bp = Blueprint("orgs", __name__)

# Level ID → key name (mirrors bootstrap LEVEL_MAP)
LEVEL_MAP = {
    9: "mlb", 8: "aaa", 7: "aa", 6: "higha", 5: "a", 4: "scraps",
    3: "college", 2: "intam", 1: "hs",
}


def _reflect_orgs_table():
    """Reflect only the organizations table and cache it on the blueprint."""
    if not hasattr(orgs_bp, "_orgs_table"):
        engine = get_engine()
        metadata = MetaData()
        orgs_table = Table("organizations", metadata, autoload_with=engine)
        setattr(orgs_bp, "_orgs_table", orgs_table)
    return getattr(orgs_bp, "_orgs_table")


def _reflect_teams_table():
    """Reflect the teams table and cache it on the blueprint."""
    if not hasattr(orgs_bp, "_teams_table"):
        engine = get_engine()
        metadata = MetaData()
        orgs_bp._teams_table = Table("teams", metadata, autoload_with=engine)
    return orgs_bp._teams_table


def _row_to_dict(row):
    return dict(row._mapping)


def reflect_view(view_name: str):
    engine = get_engine()
    md = MetaData()
    vw = Table(view_name, md, autoload_with=engine)
    return vw


def _build_teams_by_org(conn):
    """Query all teams and return {org_id: {level_name: team_dict}}."""
    teams_table = _reflect_teams_table()
    rows = conn.execute(select(teams_table)).all()

    teams_by_org = {}
    for r in rows:
        td = _row_to_dict(r)
        org_id = td["orgID"]
        level_name = LEVEL_MAP.get(td["team_level"], "level_%s" % td["team_level"])
        team_name = td.get("team_name") or ""
        team_nick = td.get("team_nickname") or ""
        teams_by_org.setdefault(org_id, {})[level_name] = {
            "team_id": td.get("id"),
            "team_full_name": f"{team_name} {team_nick}".strip() or None,
            "team_nickname": td.get("team_nickname"),
            "team_abbrev": td.get("team_abbrev"),
            "team_city": td.get("team_city"),
            "team_level": td.get("team_level"),
            "org_id": org_id,
            "conference": td.get("conference"),
            "division": td.get("division"),
            "color_one": td.get("color_one"),
            "color_two": td.get("color_two"),
            "color_three": td.get("color_three"),
        }
    return teams_by_org


def shape_org_report(org_dict: dict, teams: dict | None = None) -> dict:
    """Shape an organization row into the org_report response format.

    Args:
        org_dict: Row from organizations table (with role columns).
        teams: Pre-built teams dict keyed by level name, or None for empty.
    """
    d = org_dict
    shaped = {
        "id": d.get("id"),
        "org_abbrev": d.get("org_abbrev"),
        "cash": d.get("cash"),
        "league": d.get("league", "mlb"),
        "teams": teams or {},
    }

    league = d.get("league", "mlb")
    if league == "mlb":
        shaped["owner_name"] = d.get("owner_name", "")
        shaped["gm_name"] = d.get("gm_name", "")
        shaped["manager_name"] = d.get("manager_name", "")
        shaped["scout_name"] = d.get("scout_name", "")
    elif league == "college":
        shaped["coach"] = d.get("coach", "AI")

    return shaped


@orgs_bp.get("/org_report/")
def get_org_report():
    """
    Return all organizations as JSON, each with fully populated teams dict.
    Teams are queried directly from the teams table so every org type
    (MLB, college, INTAM, HS) gets its teams populated.
    """
    try:
        orgs_table = _reflect_orgs_table()
        engine = get_engine()

        with engine.connect() as conn:
            # All orgs with role/coach columns
            org_rows = conn.execute(select(orgs_table)).all()

            # All teams grouped by org_id
            teams_by_org = _build_teams_by_org(conn)

        data = []
        for r in org_rows:
            d = _row_to_dict(r)
            org_id = d["id"]
            data.append(shape_org_report(d, teams=teams_by_org.get(org_id)))

        return jsonify(data), 200
    except SQLAlchemyError:
        return jsonify({
            "error": {"code": "db_unavailable", "message": "Database temporarily unavailable"}
        }), 503

@orgs_bp.get("/organizations")
# @rate_limit() # Reuse your project’s default limiter if available
def list_organizations():
    """Return a JSON array of org_abbrev strings, sorted alphabetically."""
    try:
        orgs_table = _reflect_orgs_table()
        engine = get_engine()
        stmt = select(orgs_table.c.org_abbrev).order_by(orgs_table.c.org_abbrev.asc())
        with engine.connect() as conn:
            rows = conn.execute(stmt).all()
        abbrevs = [r[0] for r in rows]
        return jsonify(abbrevs), 200
    except SQLAlchemyError:
    # Server/DB error envelope (not a 200)
        return jsonify({
            "error": {
            "code": "db_unavailable",
            "message": "Database temporarily unavailable"
            }
        }), 503

@orgs_bp.get("/<string:org>/")
# @rate_limit() # Reuse your project’s default limiter if available
def get_organization(org: str):
    """Case-insensitive lookup by org_abbrev. Returns [] if not found, or [row]."""
    try:
        orgs_table = _reflect_orgs_table()
        engine = get_engine()
        # Normalize to uppercase for matching without changing DB
        org_upper = (org or "").upper()
        # Use a case-insensitive comparison by uppercasing the column too
        stmt = (
            select(orgs_table)
            .where(text("UPPER(org_abbrev) = :org_upper")).limit(1)
        )
        with engine.connect() as conn:
            row = conn.execute(stmt, {"org_upper": org_upper}).first()
        if not row:
            return jsonify([]), 200
        return jsonify([_row_to_dict(row)]), 200
    except SQLAlchemyError:
        return jsonify({
            "error": {
            "code": "db_unavailable",
            "message": "Database temporarily unavailable"
            }
        }), 503