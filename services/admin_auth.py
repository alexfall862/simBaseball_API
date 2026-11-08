# services/admin_auth.py
"""
Admin guard for season-mutating /api/v1 routes (plan item B6).

Accepted credentials (any one):
  * the admin session cookie (set by POST /admin/login)
  * header X-Admin-Password == ADMIN_PASSWORD
  * header X-Admin-Key == ADMIN_API_KEY (for scripts / the scheduler container)

If neither ADMIN_PASSWORD nor ADMIN_API_KEY is configured the guard allows
everything (local development), mirroring /admin/login's behaviour.
Set ADMIN_ROUTE_GUARD=off to disable the guard entirely.

The protected list is explicit on purpose: only operations that advance,
reset or roll over the league. Player-facing routes are untouched.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable, Tuple

from flask import jsonify, request, session

log = logging.getLogger(__name__)

# (method, path prefix under /api/v1). A request matches when the method is
# equal and the path starts with the prefix.
PROTECTED: Tuple[Tuple[str, str], ...] = (
    # games — simulation & calendar
    ("POST", "/api/v1/games/simulate-week"),
    ("POST", "/api/v1/games/simulate-subweek"),
    ("POST", "/api/v1/games/advance-week"),
    ("POST", "/api/v1/games/run-week"),
    ("POST", "/api/v1/games/run-season"),
    ("POST", "/api/v1/games/reset-week"),
    ("POST", "/api/v1/games/rollback-week"),
    ("POST", "/api/v1/games/rollback-to-week"),
    ("POST", "/api/v1/games/wipe-season"),
    ("POST", "/api/v1/games/stamina-rest"),
    ("POST", "/api/v1/games/set-week"),
    ("POST", "/api/v1/games/set-phase"),
    ("POST", "/api/v1/games/end-season"),
    ("POST", "/api/v1/games/start-free-agency"),
    ("POST", "/api/v1/games/advance-fa-round"),
    ("POST", "/api/v1/games/end-free-agency"),
    ("POST", "/api/v1/games/start-draft"),
    ("POST", "/api/v1/games/end-draft"),
    ("POST", "/api/v1/games/start-recruiting"),
    ("POST", "/api/v1/games/end-recruiting"),
    ("POST", "/api/v1/games/start-new-season"),
    ("DELETE", "/api/v1/games/tasks/"),
    # playoffs — bracket mutations
    ("POST", "/api/v1/playoffs/generate"),
    ("POST", "/api/v1/playoffs/advance"),
    ("POST", "/api/v1/playoffs/process-results"),
    ("POST", "/api/v1/playoffs/process-and-advance"),
    ("POST", "/api/v1/playoffs/conf-tournaments/"),
    ("POST", "/api/v1/playoffs/update-series"),
    ("POST", "/api/v1/playoffs/set-matchups"),
    ("POST", "/api/v1/playoffs/wipe"),
    ("POST", "/api/v1/playoffs/reschedule-game"),
    # market windows
    ("POST", "/api/v1/recruiting/advance-week"),
    ("POST", "/api/v1/recruiting/rankings/regenerate"),
    ("POST", "/api/v1/recruiting/admin/"),
    ("POST", "/api/v1/ifa/advance-week"),
    ("POST", "/api/v1/ifa/reset"),
    ("POST", "/api/v1/ifa/auction/start"),
    ("POST", "/api/v1/fa-auction/advance-phases"),
    ("POST", "/api/v1/fa-auction/admin/"),
    ("POST", "/api/v1/transactions/end-of-season"),
    # player engine
    ("POST", "/api/v1/player-ops/progress-all"),
    # awards (admin-entered)
    ("POST", "/api/v1/awards/sync-postseason"),
)


def _enabled() -> bool:
    return os.getenv("ADMIN_ROUTE_GUARD", "on").lower() not in ("off", "0", "false", "no")


def _credentials_configured() -> bool:
    return bool(os.getenv("ADMIN_PASSWORD") or os.getenv("ADMIN_API_KEY"))


def is_admin_request() -> bool:
    if session.get("admin") is True:
        return True
    pw = os.getenv("ADMIN_PASSWORD", "")
    if pw and request.headers.get("X-Admin-Password") == pw:
        return True
    key = os.getenv("ADMIN_API_KEY", "")
    if key and request.headers.get("X-Admin-Key") == key:
        return True
    return False


def _matches(method: str, path: str, rules: Iterable[Tuple[str, str]]) -> bool:
    for m, prefix in rules:
        if m == method and path.startswith(prefix):
            return True
    return False


def install_admin_route_guard(app) -> None:
    """Register a before_request hook that 401s unauthenticated calls to PROTECTED routes."""
    if not _enabled():
        log.info("admin route guard disabled by ADMIN_ROUTE_GUARD")
        return

    @app.before_request
    def _admin_route_guard():  # noqa: D401
        if request.method == "OPTIONS":
            return None
        if not _matches(request.method, request.path, PROTECTED):
            return None
        if not _credentials_configured():
            return None  # local dev: nothing to check against
        if is_admin_request():
            return None
        log.info("admin route guard: denied %s %s from %s", request.method, request.path, request.remote_addr)
        return jsonify(error="unauthorized",
                       message="This operation requires the admin session, X-Admin-Password or X-Admin-Key."), 401

    log.info("admin route guard installed (%d rules)", len(PROTECTED))
