"""
Admin org-seat management (admin/routes_assignments.py).

Runs against SIMBB_TEST_DATABASE_URL (a copy of the league database, e.g. the
rehearsal copy). Every endpoint is pointed at one connection inside an outer
transaction that is rolled back, so nothing persists.
"""
import os
from contextlib import contextmanager

import pytest
from flask import Flask

DB_URL = os.getenv("SIMBB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="SIMBB_TEST_DATABASE_URL not set")


class _TxEngine:
    """Engine stand-in: connect() and begin() share one connection; begin() is a savepoint."""

    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def connect(self):
        yield self.conn

    @contextmanager
    def begin(self):
        sp = self.conn.begin_nested()
        try:
            yield self.conn
        except Exception:
            sp.rollback()
            raise
        sp.commit()


@pytest.fixture
def env(monkeypatch):
    from sqlalchemy import create_engine, text
    import admin
    from admin import routes_assignments as ra

    eng = create_engine(DB_URL, pool_pre_ping=True)
    with eng.connect() as conn:
        tx = conn.begin()
        try:
            mlb = conn.execute(text("SELECT id FROM organizations WHERE league='mlb' ORDER BY id LIMIT 2")).scalars().all()
            col = conn.execute(text("SELECT id FROM organizations WHERE league='college' ORDER BY id LIMIT 1")).scalar()
            if len(mlb) < 2 or not col:
                pytest.skip("needs two MLB orgs and one college org")
            # Known starting state for the orgs under test.
            conn.execute(text("""UPDATE organizations SET owner_name='', gm_name='', manager_name='', scout_name=''
                                 WHERE id IN (:a, :b)"""), {"a": mlb[0], "b": mlb[1]})
            conn.execute(text("UPDATE organizations SET coach='AI' WHERE id=:c"), {"c": col})
            monkeypatch.setattr(ra, "_engine", lambda: _TxEngine(conn))

            app = Flask(__name__)
            app.secret_key = "t"
            app.register_blueprint(admin.admin_bp)
            client = app.test_client()
            with client.session_transaction() as s:
                s["admin"] = True
            yield {"c": client, "conn": conn, "mlb": mlb, "col": col, "text": text}
        finally:
            tx.rollback()


def _seat(env, org_id, col):
    t = env["text"]
    return env["conn"].execute(t(f"SELECT {col} FROM organizations WHERE id=:o"), {"o": org_id}).scalar()


def test_requires_admin_session(env):
    app_client = env["c"]
    with app_client.session_transaction() as s:
        s.clear()
    assert app_client.get("/admin/assignments").status_code == 401
    assert app_client.post("/admin/assignments/set", json={}).status_code == 401


def test_list_shapes_seats(env):
    r = env["c"].get("/admin/assignments")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    a = next(o for o in d["mlb"] if o["org_id"] == env["mlb"][0])
    assert a["seats"] == {"o": "", "gm": "", "mgr": "", "sc": ""}
    c = next(o for o in d["college"] if o["org_id"] == env["col"])
    assert c["seats"] == {"coach": ""}  # 'AI' shown as vacant
    assert d["roles"]["mlb"]["gm"] == "GM"
    assert isinstance(d["pending"], list)


def test_set_conflict_overwrite_and_clear(env):
    c, org = env["c"], env["mlb"][0]
    r = c.post("/admin/assignments/set", json={"org_id": org, "role": "gm", "username": "alice"})
    assert r.status_code == 200 and r.get_json()["previous"] is None
    assert _seat(env, org, "gm_name") == "alice"

    r = c.post("/admin/assignments/set", json={"org_id": org, "role": "gm", "username": "bob"})
    assert r.status_code == 409 and r.get_json()["error"] == "seat_taken"
    assert r.get_json()["holder"] == "alice"
    assert _seat(env, org, "gm_name") == "alice"

    r = c.post("/admin/assignments/set", json={"org_id": org, "role": "gm", "username": "bob", "overwrite": True})
    assert r.status_code == 200 and r.get_json()["previous"] == "alice"
    assert _seat(env, org, "gm_name") == "bob"

    r = c.post("/admin/assignments/set", json={"org_id": org, "role": "gm", "username": ""})
    assert r.status_code == 200 and r.get_json()["previous"] == "bob"
    assert _seat(env, org, "gm_name") == ""


def test_set_rejects_bad_role_and_league(env):
    c = env["c"]
    r = c.post("/admin/assignments/set", json={"org_id": env["mlb"][0], "role": "coach", "username": "x"})
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_role"
    r = c.post("/admin/assignments/set", json={"org_id": env["col"], "role": "gm", "username": "x"})
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_role"
    r = c.post("/admin/assignments/set", json={"org_id": 99999999, "role": "gm", "username": "x"})
    assert r.status_code == 404


def test_college_clear_restores_ai(env):
    c, org = env["c"], env["col"]
    assert c.post("/admin/assignments/set", json={"org_id": org, "role": "coach", "username": "coachy"}).status_code == 200
    assert _seat(env, org, "coach") == "coachy"
    r = c.post("/admin/assignments/set", json={"org_id": org, "role": "coach", "username": ""})
    assert r.status_code == 200 and r.get_json()["previous"] == "coachy"
    assert _seat(env, org, "coach") == "AI"


def test_move_between_orgs_and_leagues(env):
    c, (a, b), col = env["c"], env["mlb"], env["col"]
    c.post("/admin/assignments/set", json={"org_id": a, "role": "o", "username": "dana"})

    r = c.post("/admin/assignments/move", json={"username": "erin", "from_org_id": a, "from_role": "o",
                                                "to_org_id": b, "to_role": "gm"})
    assert r.status_code == 409 and r.get_json()["error"] == "not_holder"

    r = c.post("/admin/assignments/move", json={"username": "dana", "from_org_id": a, "from_role": "o",
                                                "to_org_id": b, "to_role": "gm"})
    assert r.status_code == 200, r.get_json()
    assert _seat(env, a, "owner_name") == "" and _seat(env, b, "gm_name") == "dana"

    # Into an occupied seat: refused, then allowed with overwrite.
    c.post("/admin/assignments/set", json={"org_id": col, "role": "coach", "username": "frank"})
    body = {"username": "dana", "from_org_id": b, "from_role": "gm", "to_org_id": col, "to_role": "coach"}
    r = c.post("/admin/assignments/move", json=body)
    assert r.status_code == 409 and r.get_json()["holder"] == "frank"
    assert _seat(env, b, "gm_name") == "dana"  # nothing changed
    r = c.post("/admin/assignments/move", json={**body, "overwrite": True})
    assert r.status_code == 200 and r.get_json()["displaced"] == "frank"
    assert _seat(env, b, "gm_name") == "" and _seat(env, col, "coach") == "dana"


def _pending(env, league, org_id, username, role="gm"):
    t, conn = env["text"], env["conn"]
    if league == "mlb":
        conn.execute(t("""INSERT INTO mlb_requests (username, org_id, role, is_approved)
                          VALUES (:u, :o, :r, 0)"""), {"u": username, "o": org_id, "r": role})
    else:
        conn.execute(t("INSERT INTO college_baseball_requests (username, org_id, is_approved) VALUES (:u, :o, 0)"),
                     {"u": username, "o": org_id})
    return conn.execute(t("SELECT LAST_INSERT_ID()")).scalar()


def test_approve_vacant_and_refuse_taken(env):
    c, org, t, conn = env["c"], env["mlb"][0], env["text"], env["conn"]
    rid = _pending(env, "mlb", org, "gina")
    listed = c.get("/admin/assignments").get_json()["pending"]
    assert any(p["league"] == "mlb" and p["id"] == rid and p["seat_holder"] is None for p in listed)

    r = c.post(f"/admin/assignments/requests/mlb/{rid}/approve")
    assert r.status_code == 200, r.get_json()
    assert _seat(env, org, "gm_name") == "gina"
    assert conn.execute(t("SELECT is_approved FROM mlb_requests WHERE id=:i"), {"i": rid}).scalar() == 1
    assert c.post(f"/admin/assignments/requests/mlb/{rid}/approve").status_code == 409  # already approved

    rid2 = _pending(env, "mlb", org, "hank")
    r = c.post(f"/admin/assignments/requests/mlb/{rid2}/approve")
    assert r.status_code == 409 and r.get_json()["holder"] == "gina"
    assert _seat(env, org, "gm_name") == "gina"
    r = c.post(f"/admin/assignments/requests/mlb/{rid2}/approve", json={"overwrite": True})
    assert r.status_code == 200 and r.get_json()["displaced"] == "gina"
    assert _seat(env, org, "gm_name") == "hank"


def test_college_approve_and_reject(env):
    c, col, t, conn = env["c"], env["col"], env["text"], env["conn"]
    rid = _pending(env, "college", col, "ivy")
    r = c.post(f"/admin/assignments/requests/college/{rid}/approve")
    assert r.status_code == 200, r.get_json()
    assert _seat(env, col, "coach") == "ivy"

    rid2 = _pending(env, "college", col, "jack")
    r = c.post(f"/admin/assignments/requests/college/{rid2}/reject")
    assert r.status_code == 200
    assert conn.execute(t("SELECT COUNT(*) FROM college_baseball_requests WHERE id=:i"), {"i": rid2}).scalar() == 0
    assert c.post("/admin/assignments/requests/nfl/1/reject").status_code == 400
