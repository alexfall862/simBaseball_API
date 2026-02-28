# college_requests/__init__.py
import logging
from flask import Blueprint, jsonify, request
from sqlalchemy import MetaData, Table, select
from sqlalchemy.exc import SQLAlchemyError
from db import get_engine

college_requests_bp = Blueprint("college_requests", __name__)
log = logging.getLogger("app")


def _reflect_table(name: str):
    cache_key = f"_{name}"
    if not hasattr(college_requests_bp, cache_key):
        engine = get_engine()
        metadata = MetaData()
        tbl = Table(name, metadata, autoload_with=engine)
        setattr(college_requests_bp, cache_key, tbl)
    return getattr(college_requests_bp, cache_key)


def _row_to_dict(row):
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# POST /api/v1/college/requests/create
# ---------------------------------------------------------------------------
@college_requests_bp.post("/college/requests/create")
def create_request():
    body = request.get_json(silent=True) or {}
    username = body.get("Username")
    org_id = body.get("OrgID")

    if not username or org_id is None:
        return jsonify(error="missing_fields", message="Username and OrgID are required."), 400

    engine = get_engine()
    requests_tbl = _reflect_table("college_baseball_requests")
    orgs_tbl = _reflect_table("organizations")

    try:
        with engine.connect() as conn:
            # 1. Validate the organization exists and is college league
            org_row = conn.execute(
                select(orgs_tbl).where(orgs_tbl.c.id == int(org_id))
            ).first()
            if not org_row:
                return jsonify(error="org_not_found", message="Organization does not exist."), 404

            org_dict = _row_to_dict(org_row)
            if org_dict.get("league") != "college":
                return jsonify(error="wrong_league", message="Organization is not a college organization."), 400

            # 2. Validate org's coach is "AI" or empty (not already claimed)
            coach = org_dict.get("coach", "")
            if coach and coach != "AI":
                return jsonify(error="org_claimed", message="Organization already has a coach."), 409

            # 3. Validate user doesn't have a pending request
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
                    is_approved=False,
                )
            )
            conn.commit()

            new_row = conn.execute(
                select(requests_tbl).where(requests_tbl.c.id == result.inserted_primary_key[0])
            ).first()

        return jsonify(_format_response(_row_to_dict(new_row))), 201

    except SQLAlchemyError:
        log.exception("college create_request: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# GET /api/v1/college/requests/all
# ---------------------------------------------------------------------------
@college_requests_bp.get("/college/requests/all")
def list_requests():
    engine = get_engine()
    requests_tbl = _reflect_table("college_baseball_requests")

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(requests_tbl).where(requests_tbl.c.is_approved == False)
            ).all()
        return jsonify([_format_response(_row_to_dict(r)) for r in rows]), 200

    except SQLAlchemyError:
        log.exception("college list_requests: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# POST /api/v1/college/requests/approve
# ---------------------------------------------------------------------------
@college_requests_bp.post("/college/requests/approve")
def approve_request():
    body = request.get_json(silent=True) or {}
    request_id = body.get("ID")

    if request_id is None:
        return jsonify(error="missing_fields", message="ID is required."), 400

    engine = get_engine()
    requests_tbl = _reflect_table("college_baseball_requests")
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

            # 2. Set is_approved = true
            conn.execute(
                requests_tbl.update()
                .where(requests_tbl.c.id == int(request_id))
                .values(is_approved=True)
            )

            # 3. Set coach on the organization to the username
            conn.execute(
                orgs_tbl.update()
                .where(orgs_tbl.c.id == req_dict["org_id"])
                .values(coach=req_dict["username"])
            )

            conn.commit()

            # 4. Return updated request
            updated = conn.execute(
                select(requests_tbl).where(requests_tbl.c.id == int(request_id))
            ).first()

        return jsonify(_format_response(_row_to_dict(updated))), 200

    except SQLAlchemyError:
        log.exception("college approve_request: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# POST /api/v1/college/requests/reject
# ---------------------------------------------------------------------------
@college_requests_bp.post("/college/requests/reject")
def reject_request():
    body = request.get_json(silent=True) or {}
    request_id = body.get("ID")

    if request_id is None:
        return jsonify(error="missing_fields", message="ID is required."), 400

    engine = get_engine()
    requests_tbl = _reflect_table("college_baseball_requests")

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
        log.exception("college reject_request: db error")
        return jsonify(error="db_unavailable", message="Database temporarily unavailable"), 503


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_response(d: dict) -> dict:
    result = {
        "ID": d.get("id"),
        "Username": d.get("username"),
        "OrgID": d.get("org_id"),
        "IsApproved": bool(d.get("is_approved")),
    }
    if d.get("created_at") is not None:
        result["CreatedAt"] = d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"])
    if d.get("updated_at") is not None:
        result["UpdatedAt"] = d["updated_at"].isoformat() if hasattr(d["updated_at"], "isoformat") else str(d["updated_at"])
    return result
