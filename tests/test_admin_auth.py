"""Tests for the admin route guard (services/admin_auth.py)."""
import importlib

import pytest
from flask import Flask, jsonify, session


def _make_app(monkeypatch, env):
    for k in ("ADMIN_PASSWORD", "ADMIN_API_KEY", "ADMIN_ROUTE_GUARD"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import services.admin_auth as aa
    importlib.reload(aa)
    app = Flask(__name__)
    app.secret_key = "t"

    @app.post("/api/v1/games/end-season")
    def end_season():
        return jsonify(ok=True)

    @app.post("/api/v1/games/simulate-week")
    def sim_week():
        return jsonify(ok=True)

    @app.get("/api/v1/games/timestamp")
    def ts():
        return jsonify(ok=True)

    @app.post("/api/v1/transactions/trade/propose")
    def propose():
        return jsonify(ok=True)

    @app.post("/login")
    def login():
        session["admin"] = True
        return jsonify(ok=True)

    aa.install_admin_route_guard(app)
    return app


def test_guard_blocks_without_credentials(monkeypatch):
    app = _make_app(monkeypatch, {"ADMIN_PASSWORD": "pw"})
    c = app.test_client()
    assert c.post("/api/v1/games/end-season").status_code == 401
    assert c.post("/api/v1/games/simulate-week").status_code == 401


def test_guard_leaves_unlisted_routes_alone(monkeypatch):
    app = _make_app(monkeypatch, {"ADMIN_PASSWORD": "pw"})
    c = app.test_client()
    assert c.get("/api/v1/games/timestamp").status_code == 200
    assert c.post("/api/v1/transactions/trade/propose").status_code == 200


def test_guard_accepts_header_key_and_session(monkeypatch):
    app = _make_app(monkeypatch, {"ADMIN_PASSWORD": "pw", "ADMIN_API_KEY": "k"})
    c = app.test_client()
    assert c.post("/api/v1/games/end-season", headers={"X-Admin-Password": "pw"}).status_code == 200
    assert c.post("/api/v1/games/end-season", headers={"X-Admin-Password": "nope"}).status_code == 401
    assert c.post("/api/v1/games/end-season", headers={"X-Admin-Key": "k"}).status_code == 200
    c.post("/login")
    assert c.post("/api/v1/games/end-season").status_code == 200


def test_guard_allows_everything_when_unconfigured(monkeypatch):
    app = _make_app(monkeypatch, {})
    c = app.test_client()
    assert c.post("/api/v1/games/end-season").status_code == 200


def test_guard_can_be_disabled(monkeypatch):
    app = _make_app(monkeypatch, {"ADMIN_PASSWORD": "pw", "ADMIN_ROUTE_GUARD": "off"})
    c = app.test_client()
    assert c.post("/api/v1/games/end-season").status_code == 200
