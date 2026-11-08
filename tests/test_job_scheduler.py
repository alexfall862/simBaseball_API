"""Unit tests for the admin job scheduler (pure parts) and the job registry.

Run:  test_env/Scripts/python.exe -m pytest tests/test_job_scheduler.py -q
DB-backed tests run only when SIMBB_TEST_DATABASE_URL is set.
"""
import os
import threading
from datetime import datetime, timezone

import pytest

from services import jobs as jobs_mod
from services.jobs import JobContext, JobSkipped, apply_defaults, get_job, list_jobs
from services.job_scheduler import compute_next_run, next_fire_times, _to_utc_naive


# ---------------------------------------------------------------- schedules
def test_cron_next_run_in_timezone():
    # 06:00 America/New_York on a normal day == 11:00 UTC (EST, UTC-5)
    after = datetime(2026, 1, 10, 12, 0)  # noon UTC -> next 06:00 NY is Jan 11 11:00 UTC
    nxt = compute_next_run("cron", "0 6 * * *", None, None, "America/New_York", after=after)
    assert nxt == datetime(2026, 1, 11, 11, 0)


def test_cron_handles_dst_change():
    # DST starts 2026-03-08 in the US: 06:00 NY becomes 10:00 UTC after the switch.
    before = compute_next_run("cron", "0 6 * * *", None, None, "America/New_York", after=datetime(2026, 3, 7, 12, 0))
    after = compute_next_run("cron", "0 6 * * *", None, None, "America/New_York", after=datetime(2026, 3, 8, 12, 0))
    assert before == datetime(2026, 3, 8, 10, 0)   # Mar 8 06:00 EDT == 10:00 UTC
    assert after == datetime(2026, 3, 9, 10, 0)


def test_cron_weekdays_only():
    # Friday 2026-01-09 13:00 UTC -> next weekday 06:00 NY is Monday Jan 12
    nxt = compute_next_run("cron", "0 6 * * 1-5", None, None, "America/New_York", after=datetime(2026, 1, 9, 13, 0))
    assert nxt == datetime(2026, 1, 12, 11, 0)


def test_interval_and_once_and_manual():
    now = datetime(2026, 1, 1, 0, 0)
    assert compute_next_run("interval", None, 3600, None, "UTC", after=now) == datetime(2026, 1, 1, 1, 0)
    assert compute_next_run("once", None, None, datetime(2026, 2, 1), "UTC", after=now) == datetime(2026, 2, 1)
    assert compute_next_run("once", None, None, datetime(2025, 2, 1), "UTC", after=now) is None
    assert compute_next_run("manual", None, None, None, "UTC", after=now) is None


def test_invalid_cron_raises():
    with pytest.raises(ValueError):
        compute_next_run("cron", "99 99 * * *", None, None, "UTC")
    with pytest.raises(ValueError):
        compute_next_run("interval", None, 0, None, "UTC")


def test_next_fire_times_count():
    fires = next_fire_times("*/15 * * * *", "UTC", n=4, after=datetime(2026, 1, 1, 0, 1))
    assert fires == ["2026-01-01T00:15:00Z", "2026-01-01T00:30:00Z", "2026-01-01T00:45:00Z", "2026-01-01T01:00:00Z"]


def test_to_utc_naive():
    aware = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    assert _to_utc_naive(aware) == datetime(2026, 1, 1, 6, 0)


# ---------------------------------------------------------------- registry
def test_registry_has_core_types_and_valid_defaults():
    names = {s.name for s in list_jobs()}
    for n in ("sim_next_subweek", "advance_week", "run_week", "end_season", "archive_season", "recruiting_advance_week"):
        assert n in names
    for spec in list_jobs():
        params = apply_defaults(spec, {})
        for k, meta in spec.params.items():
            if "default" in meta:
                assert k in params


def test_apply_defaults_coerces_types():
    spec = get_job("sim_next_subweek")
    p = apply_defaults(spec, {"auto_advance": "false", "playoff_levels": "9,8", "league_level": "9"})
    assert p["auto_advance"] is False
    assert p["playoff_levels"] == [9, 8]
    assert p["league_level"] == 9
    with pytest.raises(ValueError):
        apply_defaults(spec, {"league_level": "nine"})


def test_next_subweek_picks_first_unset():
    f = jobs_mod._next_subweek
    assert f({"GamesARan": False}) == "a"
    assert f({"GamesARan": True, "GamesBRan": False}) == "b"
    assert f({"GamesARan": True, "GamesBRan": True, "GamesCRan": True, "GamesDRan": False}) == "d"
    assert f({"GamesARan": True, "GamesBRan": True, "GamesCRan": True, "GamesDRan": True}) is None


def test_sim_next_subweek_skips_when_run_games(monkeypatch):
    ctx = JobContext(engine=None, params=apply_defaults(get_job("sim_next_subweek"), {}))
    ctx._ts = {"Phase": "REGULAR_SEASON", "RunGames": True, "Week": 5, "LeagueYearID": 1}
    monkeypatch.setattr(JobContext, "timestamp", lambda self, refresh=False: self._ts)
    with pytest.raises(JobSkipped):
        jobs_mod.sim_next_subweek(ctx)


def test_sim_next_subweek_advances_when_all_done(monkeypatch):
    calls = {}
    import services.timestamp as ts_mod
    monkeypatch.setattr(ts_mod, "advance_week", lambda broadcast=True: calls.setdefault("adv", True))
    ctx = JobContext(engine=None, params=apply_defaults(get_job("sim_next_subweek"), {}))
    ctx._ts = {"Phase": "REGULAR_SEASON", "RunGames": False, "Week": 5, "LeagueYearID": 1,
               "GamesARan": True, "GamesBRan": True, "GamesCRan": True, "GamesDRan": True}
    # timestamp(refresh=True) is called inside; keep our stub
    monkeypatch.setattr(JobContext, "timestamp", lambda self, refresh=False: self._ts)
    out = jobs_mod.sim_next_subweek(ctx)
    assert calls.get("adv") is True
    assert out["advanced_to"] == 6


def test_sim_next_subweek_skips_when_done_and_no_auto_advance(monkeypatch):
    ctx = JobContext(engine=None, params=apply_defaults(get_job("sim_next_subweek"), {"auto_advance": False}))
    ctx._ts = {"Phase": "REGULAR_SEASON", "RunGames": False, "Week": 5, "LeagueYearID": 1,
               "GamesARan": True, "GamesBRan": True, "GamesCRan": True, "GamesDRan": True}
    monkeypatch.setattr(JobContext, "timestamp", lambda self, refresh=False: self._ts)
    with pytest.raises(JobSkipped):
        jobs_mod.sim_next_subweek(ctx)


# ---------------------------------------------------------------- DB-backed
DB_URL = os.getenv("SIMBB_TEST_DATABASE_URL")


@pytest.mark.skipif(not DB_URL, reason="SIMBB_TEST_DATABASE_URL not set")
def test_claim_race_only_one_winner():
    from sqlalchemy import create_engine
    from services.job_scheduler import ensure_schema, enqueue_run, _claim_run, _finish_run

    eng = create_engine(DB_URL, pool_pre_ping=True)
    ensure_schema(eng)
    run_id = enqueue_run(eng, "trade_queue_digest", {}, "manual")
    winners = []

    def worker():
        if _claim_run(eng, run_id):
            winners.append(threading.get_ident())

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1
    _finish_run(eng, run_id, "cancelled", error="test cleanup")


@pytest.mark.skipif(not DB_URL, reason="SIMBB_TEST_DATABASE_URL not set")
def test_execute_run_records_summary():
    from sqlalchemy import create_engine
    from services.job_scheduler import ensure_schema, enqueue_run, execute_run, get_run

    eng = create_engine(DB_URL, pool_pre_ping=True)
    ensure_schema(eng)
    run_id = enqueue_run(eng, "trade_queue_digest", {}, "manual")
    status = execute_run(eng, run_id)
    run = get_run(eng, run_id)
    assert status == "succeeded"
    assert run["summary"] is not None and "awaiting_approval" in run["summary"]
    assert run["task_id"]
    assert "start trade_queue_digest" in (run.get("log_text") or "")
