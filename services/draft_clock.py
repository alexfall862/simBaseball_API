# services/draft_clock.py
"""
Server-side draft pick clock.

One daemon thread per process polls for a live draft whose current pick has
run past ``pick_deadline_at`` and auto-picks for it (the same path the lazy,
request-driven ``check_timer_expiry`` used), so the clock no longer depends
on a client polling the API.

Leader election: each thread tries ``GET_LOCK('simbb_draft_clock', 0)`` on a
dedicated connection. MySQL hands the named lock to exactly one session, so
with several gunicorn workers / processes only one of them ticks; the others
retry every ``_FOLLOWER_RETRY_S`` seconds and take over if the leader dies
(the lock is released when its connection drops).

Disable with ``DRAFT_CLOCK_DISABLED=1``.
"""

import logging
import os
import threading
import time

from sqlalchemy import text

log = logging.getLogger("app")

_LOCK_NAME = "simbb_draft_clock"
_TICK_S = float(os.getenv("DRAFT_CLOCK_TICK_S", "3"))
_FOLLOWER_RETRY_S = 20.0
_started = False
_start_lock = threading.Lock()


def start_draft_clock(get_engine) -> bool:
    """Start the ticker thread once per process. Returns True if started."""
    global _started
    if os.getenv("DRAFT_CLOCK_DISABLED", "").lower() in ("1", "true", "yes"):
        return False
    # Under the werkzeug reloader the parent process only supervises.
    if os.getenv("FLASK_ENV") == "development" and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    with _start_lock:
        if _started:
            return False
        _started = True
    t = threading.Thread(target=_run, args=(get_engine,), name="draft-clock", daemon=True)
    t.start()
    return True


def _run(get_engine) -> None:
    time.sleep(2.0)   # let the app finish booting
    while True:
        try:
            engine = get_engine()
        except Exception as e:
            log.warning("draft clock: no engine yet (%s)", e)
            time.sleep(_FOLLOWER_RETRY_S)
            continue
        try:
            with engine.connect() as lock_conn:
                got = lock_conn.execute(
                    text("SELECT GET_LOCK(:n, 0)"), {"n": _LOCK_NAME}).scalar()
                if not got:
                    time.sleep(_FOLLOWER_RETRY_S)
                    continue
                log.info("draft clock: this process is the leader")
                try:
                    _lead(engine, lock_conn)
                finally:
                    try:
                        lock_conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": _LOCK_NAME})
                    except Exception:
                        pass
        except Exception as e:
            log.warning("draft clock: leader loop ended: %s", e)
            time.sleep(_FOLLOWER_RETRY_S)


def _lead(engine, lock_conn) -> None:
    """Tick while we hold the lock. Any DB error returns to re-election."""
    from services.draft import check_timer_expiry
    while True:
        # Keep the lock connection alive (and detect a dropped session).
        lock_conn.execute(text("SELECT 1"))
        with engine.connect() as conn:
            due = conn.execute(text("""
                SELECT league_year_id FROM draft_state
                WHERE phase = 'IN_PROGRESS'
                  AND pick_deadline_at IS NOT NULL
                  AND pick_deadline_at <= UTC_TIMESTAMP()
            """)).all()
        for (lyid,) in due:
            try:
                with engine.begin() as conn:
                    made = check_timer_expiry(conn, int(lyid))
                if made:
                    log.info("draft clock: %d expired pick(s) auto-picked (year %s)",
                             len(made), lyid)
            except Exception as e:
                log.warning("draft clock: auto-pick failed for year %s: %s", lyid, e)
        time.sleep(_TICK_S)
