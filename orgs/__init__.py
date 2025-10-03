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

@orgs_bp.get("/org_report")
def get_org_details():
    try:
        vw = reflect_view("organization_report")
        stmt = select(vw)
        with get_engine().connect() as conn:
            row = conn.execute(stmt).first()
        return jsonify([] if not row else [dict(row._mapping)]), 200
    except SQLAlchemyError:
        return jsonify({"error": {"code": "db_unavailable", "message": "Database temporarily unavailable"}}), 503



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