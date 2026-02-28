# mlb_requests/__init__.py
import logging
from flask import Blueprint, jsonify, request
from sqlalchemy import MetaData, Table, select
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

mlb_requests_bp = Blueprint("mlb_requests", __name__)
log = logging.getLogger("app")

# Maps role code -> column name on the organizations table
ROLE_TO_COLUMN = {
    "o":   "owner_name",
    "gm":  "gm_name",
    "mgr": "manager_name",
    "sc":  "scout_name",
}


def _reflect_table(name: str):
    cache_key = f"_{name}"
    if not hasattr(mlb_requests_bp, cache_key):
        engine = get_engine()
        metadata = MetaData()
        tbl = Table(name, metadata, autoload_with=engine)
        setattr(mlb_requests_bp, cache_key, tbl)
    return getattr(mlb_requests_bp, cache_key)


def _row_to_dict(row):
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# POST /api/v1/mlb/requests/create
# ---------------------------------------------------------------------------
@mlb_requests_bp.post("/mlb/requests/create")
def create_request():
    body = request.get_json(silent=True) or {}
    username = body.get("Username")
    org_id = body.get("OrgID")
    role = body.get("Role")

    if not username or org_id is None or not role:
        return jsonify(error="missing_fields", message="Username, OrgID, and Role are required."), 400

    if role not in ROLE_TO_COLUMN:
        return jsonify(error="invalid_role", message=f"Role must be one of: {', '.join(ROLE_TO_COLUMN.keys())}"), 400

    engine = get_engine()
    requests_tbl = _reflect_table("mlb_requests")
    orgs_tbl = _reflect_table("organizations")

    try:
        with engine.connect() as conn:
            # 1. Validate the organization exists and is MLB league
            org_row = conn.execute(
                select(orgs_tbl).where(orgs_tbl.c.id == int(org_id))
            ).first()
            if not org_row:
                return jsonify(error="org_not_found", message="Organization does not exist."), 404

            org_dict = _row_to_dict(org_row)
            if org_dict.get("league") != "mlb":
                return jsonify(error="wrong_league", message="Organization is not an MLB organization."), 400

            # 2. Validate the requested role is vacant
            role_col = ROLE_TO_COLUMN[role]
            current_holder = org_dict.get(role_col, "")
            if current_holder:
                return jsonify(error="role_taken", message=f"The {role} role is already filled."), 409

            # 3. Validate user doesn't already have a pending request
            pending = conn.execute(
                select(requests_tbl).where(
                    (requests_tbl.c.username == username)
                    & (requests_tbl.c.is_approved == False)
                )
            ).first()
            if pending:
                return jsonify(error="pending_exists", message="User already has a pending request."), 409

            # 4. Create the request record
            result = conn.execute(
                requests_tbl.insert().values(
                    username=username,
                    org_id=int(org_id),
                    role=role,
                    is_owner=bool(body.get("IsOwner", False)),
                    is_gm=bool(body.get("IsGM", False)),
                    is_manager=bool(body.get("IsManager", False)),
                    is_scout=bool(body.get("IsScout", False)),
                    is_approved=False,
                )
            )
            conn.commit()

            new_row = conn.execute(
                select(requests_tbl).where(requests_tbl.c.id == result.inserted_primary_key[0])
            ).first()

        return jsonify(_format_response(_row_to_dict(new_row))), 201

    except SQLAlchemyError:
        log.exception("mlb create_request: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# GET /api/v1/mlb/requests/all
# ---------------------------------------------------------------------------
@mlb_requests_bp.get("/mlb/requests/all")
def list_requests():
    engine = get_engine()
    requests_tbl = _reflect_table("mlb_requests")

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(requests_tbl).where(requests_tbl.c.is_approved == False)
            ).all()
        return jsonify([_format_response(_row_to_dict(r)) for r in rows]), 200

    except SQLAlchemyError:
        log.exception("mlb list_requests: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# POST /api/v1/mlb/requests/approve
# ---------------------------------------------------------------------------
@mlb_requests_bp.post("/mlb/requests/approve")
def approve_request():
    body = request.get_json(silent=True) or {}
    request_id = body.get("ID")

    if request_id is None:
        return jsonify(error="missing_fields", message="ID is required."), 400

    engine = get_engine()
    requests_tbl = _reflect_table("mlb_requests")
    orgs_tbl = _reflect_table("organizations")

    try:
        with engine.connect() as conn:
            # 1. Find the request
            req_row = conn.execute(
                select(requests_tbl).where(requests_tbl.c.id == int(request_id))
            ).first()
            if not req_row:
                return jsonify(error="request_not_found", message="Request not found."), 404

            req_dict = _row_to_dict(req_row)
            role = req_dict["role"]

            if role not in ROLE_TO_COLUMN:
                return jsonify(error="invalid_role", message="Request has an invalid role."), 400

            # 2. Set is_approved = true
            conn.execute(
                requests_tbl.update()
                .where(requests_tbl.c.id == int(request_id))
                .values(is_approved=True)
            )

            # 3. Set the role field on the organization
            role_col = ROLE_TO_COLUMN[role]
            conn.execute(
                orgs_tbl.update()
                .where(orgs_tbl.c.id == req_dict["org_id"])
                .values(**{role_col: req_dict["username"]})
            )

            conn.commit()

            # 4. Return updated request
            updated = conn.execute(
                select(requests_tbl).where(requests_tbl.c.id == int(request_id))
            ).first()

        return jsonify(_format_response(_row_to_dict(updated))), 200

    except SQLAlchemyError:
        log.exception("mlb approve_request: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# POST /api/v1/mlb/requests/reject
# ---------------------------------------------------------------------------
@mlb_requests_bp.post("/mlb/requests/reject")
def reject_request():
    body = request.get_json(silent=True) or {}
    request_id = body.get("ID")

    if request_id is None:
        return jsonify(error="missing_fields", message="ID is required."), 400

    engine = get_engine()
    requests_tbl = _reflect_table("mlb_requests")

    try:
        with engine.connect() as conn:
            req_row = conn.execute(
                select(requests_tbl).where(requests_tbl.c.id == int(request_id))
            ).first()
            if not req_row:
                return jsonify(error="request_not_found", message="Request not found."), 404

            req_dict = _row_to_dict(req_row)

            conn.execute(
                requests_tbl.delete().where(requests_tbl.c.id == int(request_id))
            )
            conn.commit()

        return jsonify(_format_response(req_dict)), 200

    except SQLAlchemyError:
        log.exception("mlb reject_request: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_response(d: dict) -> dict:
    """Shape the response to match the frontend's expected key casing."""
    result = {
        "ID": d.get("id"),
        "Username": d.get("username"),
        "OrgID": d.get("org_id"),
        "Role": d.get("role"),
        "IsOwner": bool(d.get("is_owner")),
        "IsGM": bool(d.get("is_gm")),
        "IsManager": bool(d.get("is_manager")),
        "IsScout": bool(d.get("is_scout")),
        "IsApproved": bool(d.get("is_approved")),
    }
    if d.get("created_at") is not None:
        result["CreatedAt"] = d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"])
    if d.get("updated_at") is not None:
        result["UpdatedAt"] = d["updated_at"].isoformat() if hasattr(d["updated_at"], "isoformat") else str(d["updated_at"])
    return result
