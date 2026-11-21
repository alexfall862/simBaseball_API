# admin/routes_assignments.py — who runs which org (admin session only).
"""
User-to-org seat management. Assignments live as plain username strings on
`organizations`:

  MLB orgs      owner_name (o), gm_name (gm), manager_name (mgr), scout_name (sc)
  College orgs  coach (coach)  -- 'AI' means CPU-controlled; clearing sets 'AI'

GET  /admin/assignments
     {ok, roles, mlb:[org], college:[org], pending:[request]}
     org     = {org_id, org_abbrev, team_name, seats:{<role>: username|""}, has_token}
     request = {league, id, username, org_id, org_abbrev, team_name, role,
                created_at, seat_holder}

POST /admin/assignments/set
     {org_id, role, username, overwrite?}   username "" clears the seat.
     409 seat_taken when held by someone else and overwrite is not true.

POST /admin/assignments/move
     {username, from_org_id, from_role, to_org_id, to_role, overwrite?}
     Clears the source seat and fills the target in one transaction.

POST /admin/assignments/requests/<league>/<id>/approve   {overwrite?}
     Same effect as the public /api/v1/<league>/requests/approve, but refuses
     (409 seat_taken) when the seat was filled after the request was made.
POST /admin/assignments/requests/<league>/<id>/reject
     Deletes the pending request (same as the public reject).

Org API tokens (services/org_auth.py) belong to the org, not the user, so
changing a seat does not rotate them. Responses carry `has_token` so the UI
can remind the admin to rotate after removing someone.
"""

import logging

from flask import jsonify, request
from sqlalchemy import text

from admin import admin_bp, _require_admin

log = logging.getLogger(__name__)

MLB_ROLES = {"o": "owner_name", "gm": "gm_name", "mgr": "manager_name", "sc": "scout_name"}
COLLEGE_ROLES = {"coach": "coach"}
ROLE_LABELS = {
    "mlb": {"o": "Owner", "gm": "GM", "mgr": "Manager", "sc": "Scout"},
    "college": {"coach": "Coach"},
}
LEAGUE_ROLES = {"mlb": MLB_ROLES, "college": COLLEGE_ROLES}
TOP_LEVEL = {"mlb": 9, "college": 3}
REQUEST_TABLES = {"mlb": "mlb_requests", "college": "college_baseball_requests"}
AI_COACH = "AI"


def _engine():
    from db import get_engine
    return get_engine()


class _Fail(Exception):
    def __init__(self, status, error, message, **extra):
        super().__init__(message)
        self.status, self.error, self.message, self.extra = status, error, message, extra

    def response(self):
        return jsonify(ok=False, error=self.error, message=self.message, **self.extra), self.status


def _seat_value(league, role, raw):
    """Stored column value -> username shown to the admin ("" when vacant)."""
    v = (raw or "").strip()
    if league == "college" and role == "coach" and v == AI_COACH:
        return ""
    return v


def _stored_value(league, role, username):
    """Username from the admin ("" to clear) -> value written to the column."""
    if league == "college" and role == "coach" and not username:
        return AI_COACH
    return username


def _org_has_token(conn, org_id):
    try:
        return conn.execute(text("SELECT 1 FROM org_api_tokens WHERE org_id = :o"),
                            {"o": int(org_id)}).first() is not None
    except Exception:  # noqa: BLE001 — table absent before the tokens migration
        return False


def _lock_org(conn, org_id):
    row = conn.execute(text("""
        SELECT id, org_abbrev, league, owner_name, gm_name, manager_name, scout_name, coach
          FROM organizations WHERE id = :o FOR UPDATE
    """), {"o": int(org_id)}).mappings().first()
    if not row:
        raise _Fail(404, "org_not_found", f"Organization {org_id} does not exist.")
    league = (row["league"] or "").lower()
    if league not in LEAGUE_ROLES:
        raise _Fail(400, "wrong_league", f"Organization {row['org_abbrev']} is league '{row['league']}', "
                                         "which has no assignable seats.")
    return dict(row), league


def _role_column(league, role):
    col = LEAGUE_ROLES[league].get(role)
    if not col:
        raise _Fail(400, "invalid_role",
                    f"Role must be one of: {', '.join(LEAGUE_ROLES[league])} for {league} orgs.")
    return col


def _write_seat(conn, org_id, league, role, username):
    col = _role_column(league, role)  # whitelisted column name
    conn.execute(text(f"UPDATE organizations SET {col} = :v WHERE id = :o"),
                 {"v": _stored_value(league, role, username), "o": int(org_id)})


def _check_vacant(org, league, role, username, overwrite):
    """Return the current holder; raise seat_taken if someone else holds it."""
    holder = _seat_value(league, role, org[_role_column(league, role)])
    if holder and holder != username and not overwrite:
        raise _Fail(409, "seat_taken",
                    f"{ROLE_LABELS[league][role]} of {org['org_abbrev']} is held by {holder}.",
                    holder=holder)
    return holder


def _int(body, key):
    try:
        return int(body.get(key))
    except (TypeError, ValueError):
        raise _Fail(400, "missing_fields", f"{key} (integer) is required.")


# ---------------------------------------------------------------------------
# GET /admin/assignments
# ---------------------------------------------------------------------------
@admin_bp.get("/assignments")
def admin_assignments_list():
    guard = _require_admin()
    if guard:
        return guard
    try:
        with _engine().connect() as conn:
            orgs = conn.execute(text("""
                SELECT o.id, o.org_abbrev, LOWER(o.league) AS league,
                       o.owner_name, o.gm_name, o.manager_name, o.scout_name, o.coach,
                       t.team_city, t.team_name, t.team_nickname
                  FROM organizations o
                  LEFT JOIN teams t
                    ON t.orgID = o.id
                   AND t.team_level = CASE LOWER(o.league) WHEN 'mlb' THEN 9 WHEN 'college' THEN 3 END
                 WHERE LOWER(o.league) IN ('mlb', 'college')
                 ORDER BY o.org_abbrev
            """)).mappings().all()

            try:
                tokens = {int(r[0]) for r in conn.execute(text("SELECT org_id FROM org_api_tokens"))}
            except Exception:  # noqa: BLE001
                tokens = set()

            out = {"mlb": [], "college": []}
            by_id = {}
            for r in orgs:
                league = r["league"]
                name = " ".join(x for x in (r["team_city"], r["team_nickname"] or r["team_name"]) if x)
                entry = {
                    "org_id": int(r["id"]),
                    "org_abbrev": r["org_abbrev"],
                    "team_name": name or None,
                    "seats": {role: _seat_value(league, role, r[col])
                              for role, col in LEAGUE_ROLES[league].items()},
                    "has_token": int(r["id"]) in tokens,
                }
                out[league].append(entry)
                by_id[entry["org_id"]] = (league, entry)

            pending = []
            for league, tbl in REQUEST_TABLES.items():
                role_sel = "role" if league == "mlb" else "'coach' AS role"
                rows = conn.execute(text(f"""
                    SELECT id, username, org_id, {role_sel}, created_at
                      FROM {tbl} WHERE is_approved = 0 ORDER BY created_at, id
                """)).mappings().all()
                for q in rows:
                    org_league, org = by_id.get(int(q["org_id"]), (None, None))
                    role = q["role"]
                    holder = None
                    if org and org_league == league:
                        holder = org["seats"].get(role) or None
                    pending.append({
                        "league": league,
                        "id": int(q["id"]),
                        "username": q["username"],
                        "org_id": int(q["org_id"]),
                        "org_abbrev": org["org_abbrev"] if org else None,
                        "team_name": org["team_name"] if org else None,
                        "role": role,
                        "created_at": q["created_at"].isoformat() if q["created_at"] else None,
                        "seat_holder": holder,
                    })
        return jsonify(ok=True, roles=ROLE_LABELS, pending=pending, **out)
    except Exception as e:  # noqa: BLE001
        log.exception("admin assignments list failed")
        return jsonify(ok=False, error="assignments_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /admin/assignments/set
# ---------------------------------------------------------------------------
@admin_bp.post("/assignments/set")
def admin_assignments_set():
    guard = _require_admin()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    try:
        org_id = _int(body, "org_id")
        role = str(body.get("role") or "").strip()
        username = str(body.get("username") or "").strip()
        overwrite = body.get("overwrite") is True
        with _engine().begin() as conn:
            org, league = _lock_org(conn, org_id)
            if league == "college" and username == AI_COACH:
                username = ""
            # Clearing ("" username) is an explicit removal, so it never needs overwrite.
            previous = _check_vacant(org, league, role, username, overwrite or not username)
            _write_seat(conn, org_id, league, role, username)
            has_token = _org_has_token(conn, org_id)
        log.info("admin assignments: org %s %s %r -> %r", org["org_abbrev"], role, previous, username)
        return jsonify(ok=True, org_id=org_id, org_abbrev=org["org_abbrev"], league=league, role=role,
                       previous=previous or None, username=username or None, has_token=has_token)
    except _Fail as f:
        return f.response()
    except Exception as e:  # noqa: BLE001
        log.exception("admin assignments set failed")
        return jsonify(ok=False, error="assignments_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /admin/assignments/move
# ---------------------------------------------------------------------------
@admin_bp.post("/assignments/move")
def admin_assignments_move():
    guard = _require_admin()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    try:
        username = str(body.get("username") or "").strip()
        if not username:
            raise _Fail(400, "missing_fields", "username is required.")
        from_org_id = _int(body, "from_org_id")
        to_org_id = _int(body, "to_org_id")
        from_role = str(body.get("from_role") or "").strip()
        to_role = str(body.get("to_role") or "").strip()
        overwrite = body.get("overwrite") is True
        if from_org_id == to_org_id and from_role == to_role:
            raise _Fail(400, "same_seat", "Source and target seats are the same.")

        with _engine().begin() as conn:
            # Lock both rows in id order so two concurrent moves cannot deadlock.
            locked = {}
            for oid in sorted({from_org_id, to_org_id}):
                locked[oid] = _lock_org(conn, oid)
            src, src_league = locked[from_org_id]
            dst, dst_league = locked[to_org_id]

            holder = _seat_value(src_league, from_role, src[_role_column(src_league, from_role)])
            if holder != username:
                raise _Fail(409, "not_holder",
                            f"{username} does not hold {ROLE_LABELS[src_league][from_role]} of "
                            f"{src['org_abbrev']} (current: {holder or 'vacant'}).", holder=holder)
            previous = _check_vacant(dst, dst_league, to_role, username, overwrite)

            _write_seat(conn, from_org_id, src_league, from_role, "")
            _write_seat(conn, to_org_id, dst_league, to_role, username)
            src_has_token = _org_has_token(conn, from_org_id)

        log.info("admin assignments: move %r %s/%s -> %s/%s (displaced %r)", username,
                 src["org_abbrev"], from_role, dst["org_abbrev"], to_role, previous)
        return jsonify(ok=True, username=username,
                       from_org_id=from_org_id, from_org_abbrev=src["org_abbrev"], from_role=from_role,
                       to_org_id=to_org_id, to_org_abbrev=dst["org_abbrev"], to_role=to_role,
                       displaced=previous or None, from_has_token=src_has_token)
    except _Fail as f:
        return f.response()
    except Exception as e:  # noqa: BLE001
        log.exception("admin assignments move failed")
        return jsonify(ok=False, error="assignments_error", message=str(e)), 500


# ---------------------------------------------------------------------------
# POST /admin/assignments/requests/<league>/<id>/approve | reject
# ---------------------------------------------------------------------------
def _load_request(conn, league, req_id, lock=False):
    tbl = REQUEST_TABLES.get(league)
    if not tbl:
        raise _Fail(400, "invalid_league", "league must be 'mlb' or 'college'.")
    role_sel = "role" if league == "mlb" else "'coach' AS role"
    row = conn.execute(text(f"""
        SELECT id, username, org_id, {role_sel}, is_approved FROM {tbl} WHERE id = :i
        {'FOR UPDATE' if lock else ''}
    """), {"i": int(req_id)}).mappings().first()
    if not row:
        raise _Fail(404, "request_not_found", "Request not found.")
    if row["is_approved"]:
        raise _Fail(409, "already_approved", "Request was already approved.")
    return tbl, dict(row)


@admin_bp.post("/assignments/requests/<league>/<int:req_id>/approve")
def admin_assignments_approve(league, req_id):
    guard = _require_admin()
    if guard:
        return guard
    body = request.get_json(silent=True) or {}
    overwrite = body.get("overwrite") is True
    try:
        with _engine().begin() as conn:
            tbl, req = _load_request(conn, league, req_id, lock=True)
            org, org_league = _lock_org(conn, req["org_id"])
            if org_league != league:
                raise _Fail(400, "wrong_league",
                            f"Organization {org['org_abbrev']} is not a {league} organization.")
            username = (req["username"] or "").strip()
            previous = _check_vacant(org, league, req["role"], username, overwrite)
            conn.execute(text(f"UPDATE {tbl} SET is_approved = 1 WHERE id = :i"), {"i": int(req_id)})
            _write_seat(conn, org["id"], league, req["role"], username)
        log.info("admin assignments: approved %s request %s (%r -> %s/%s, displaced %r)",
                 league, req_id, username, org["org_abbrev"], req["role"], previous)
        return jsonify(ok=True, league=league, id=req_id, username=username, org_id=int(org["id"]),
                       org_abbrev=org["org_abbrev"], role=req["role"], displaced=previous or None)
    except _Fail as f:
        return f.response()
    except Exception as e:  # noqa: BLE001
        log.exception("admin assignments approve failed")
        return jsonify(ok=False, error="assignments_error", message=str(e)), 500


@admin_bp.post("/assignments/requests/<league>/<int:req_id>/reject")
def admin_assignments_reject(league, req_id):
    guard = _require_admin()
    if guard:
        return guard
    try:
        with _engine().begin() as conn:
            tbl, req = _load_request(conn, league, req_id, lock=True)
            conn.execute(text(f"DELETE FROM {tbl} WHERE id = :i"), {"i": int(req_id)})
        log.info("admin assignments: rejected %s request %s (%r)", league, req_id, req["username"])
        return jsonify(ok=True, league=league, id=req_id, username=req["username"])
    except _Fail as f:
        return f.response()
    except Exception as e:  # noqa: BLE001
        log.exception("admin assignments reject failed")
        return jsonify(ok=False, error="assignments_error", message=str(e)), 500
