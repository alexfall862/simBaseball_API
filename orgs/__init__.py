# orgs/__init__.py
from flask import Blueprint, jsonify
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine


orgs_bp = Blueprint("orgs", __name__)


# Optional: If you have a global rate limit decorator, import and use it.
# from app import rate_limit # Uncomment if available and won’t cause circular imports


def _reflect_orgs_table():
    """Reflect only the organizations table and cache it on the blueprint."""
    if not hasattr(orgs_bp, "_orgs_table"):
        engine = get_engine()
        metadata = MetaData()
        # Reflect only the one table we need
        orgs_table = Table("organizations", metadata, autoload_with=engine)
        setattr(orgs_bp, "_orgs_table", orgs_table)
    return getattr(orgs_bp, "_orgs_table")

def _row_to_dict(row):
# row is a RowMapping with ._mapping in SQLAlchemy 2.x
    return dict(row._mapping)

def reflect_view(view_name: str):
    engine = get_engine()
    md = MetaData()
    vw = Table(view_name, md, autoload_with=engine)
    return vw



def shape_org_report(row_dict: dict, role_overrides: dict | None = None) -> dict:
    d = row_dict
    if role_overrides:
        d = {**row_dict, **role_overrides}

    shaped = {
        "id": d.get("id"),
        "org_abbrev": d.get("org_abbrev"),
        "cash": d.get("cash"),
        "league": d.get("league", "mlb"),
        "teams": {
            "mlb": {
                "team_id": d.get("mlb_team_id"),
                "team_city": d.get("mlb_city"),
                "team_nickname": d.get("mlb_nickname"),
                "team_full_name": d.get("mlb_full_name"),
                "team_abbrev": d.get("mlb_abbrev")
            },
            "aaa": {
                "team_id": d.get("aaa_team_id"),
                "team_city": d.get("aaa_city"),
                "team_nickname": d.get("aaa_nickname"),
                "team_full_name": d.get("aaa_full_name"),
                "team_abbrev": d.get("aaa_abbrev")
            },
            "aa": {
                "team_id": d.get("aa_team_id"),
                "team_city": d.get("aa_city"),
                "team_nickname": d.get("aa_nickname"),
                "team_full_name": d.get("aa_full_name"),
                "team_abbrev": d.get("aa_abbrev")
            },
            "higha": {
                "team_id": d.get("higha_team_id"),
                "team_city": d.get("higha_city"),
                "team_nickname": d.get("higha_nickname"),
                "team_full_name": d.get("higha_full_name"),
                "team_abbrev": d.get("higha_abbrev")
            },
            "a": {
                "team_id": d.get("a_team_id"),
                "team_city": d.get("a_city"),
                "team_nickname": d.get("a_nickname"),
                "team_full_name": d.get("a_full_name"),
                "team_abbrev": d.get("a_abbrev")
            },
            "scraps": {
                "team_id": d.get("scraps_team_id"),
                "team_city": d.get("scraps_city"),
                "team_nickname": d.get("scraps_nickname"),
                "team_full_name": d.get("scraps_full_name"),
                "team_abbrev": d.get("scraps_abbrev")
            }
        }
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
# @rate_limit()  # uncomment to apply your default rate limits
def get_org_report():
    """
    Return all rows from the MySQL view `organization_report` as JSON,
    enriched with role/coach columns from the organizations table.
    """
    try:
        vw = reflect_view("organization_report")
        orgs_table = _reflect_orgs_table()
        engine = get_engine()

        with engine.connect() as conn:
            view_rows = conn.execute(select(vw)).all()

            # Fetch role columns that may not be in the view yet
            role_stmt = select(
                orgs_table.c.id,
                orgs_table.c.league,
                orgs_table.c.owner_name,
                orgs_table.c.gm_name,
                orgs_table.c.manager_name,
                orgs_table.c.scout_name,
                orgs_table.c.coach,
            )
            role_rows = conn.execute(role_stmt).all()

        role_map = {}
        for r in role_rows:
            rd = _row_to_dict(r)
            role_map[rd["id"]] = rd

        data = []
        for r in view_rows:
            d = _row_to_dict(r)
            overrides = role_map.get(d.get("id"))
            data.append(shape_org_report(d, role_overrides=overrides))

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