# services/org_auth.py
"""
Per-club API tokens for club-scoped writes (free agency offers first).

Each MLB org can be issued one secret token by the admin. A request that acts
for an org sends it in the ``X-Org-Token`` header; the server stores only a
SHA-256 hash. Admin credentials (session, X-Admin-Password, X-Admin-Key) may
act for any org.

Enforcement is controlled by the ``ORG_TOKEN_MODE`` environment variable:

  off      no check
  warn     (default) check, log a warning on a missing or wrong token, allow
  enforce  reject with 401 unless the token matches the org (or admin)

Start in ``warn`` until the interface sends tokens, then switch to ``enforce``.
"""
import hashlib
import hmac
import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from flask import jsonify, request
from sqlalchemy import text

log = logging.getLogger("app")

HEADER = "X-Org-Token"


def mode() -> str:
    m = (os.getenv("ORG_TOKEN_MODE") or "warn").strip().lower()
    return m if m in ("off", "warn", "enforce") else "warn"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(conn, org_id: int) -> Dict[str, Any]:
    """Create or rotate the org's token. The plain token is returned once."""
    token = secrets.token_urlsafe(32)
    conn.execute(text("""
        INSERT INTO org_api_tokens (org_id, token_hash, token_hint)
        VALUES (:o, :h, :hint)
        ON DUPLICATE KEY UPDATE token_hash = VALUES(token_hash),
                                token_hint = VALUES(token_hint),
                                rotated_at = CURRENT_TIMESTAMP,
                                last_used_at = NULL
    """), {"o": int(org_id), "h": _hash(token), "hint": token[:6]})
    return {"org_id": int(org_id), "token": token, "hint": token[:6]}


def revoke_token(conn, org_id: int) -> bool:
    return conn.execute(text("DELETE FROM org_api_tokens WHERE org_id = :o"),
                        {"o": int(org_id)}).rowcount > 0


def list_tokens(conn) -> List[Dict[str, Any]]:
    rows = conn.execute(text("""
        SELECT o.id AS org_id, o.org_abbrev, t.token_hint, t.created_at, t.rotated_at, t.last_used_at
        FROM organizations o
        LEFT JOIN org_api_tokens t ON t.org_id = o.id
        WHERE o.id BETWEEN 1 AND 30
        ORDER BY o.id
    """)).mappings().all()
    return [{"org_id": int(r["org_id"]), "org_abbrev": r["org_abbrev"],
             "has_token": r["token_hint"] is not None, "hint": r["token_hint"],
             "created_at": str(r["created_at"]) if r["created_at"] else None,
             "rotated_at": str(r["rotated_at"]) if r["rotated_at"] else None,
             "last_used_at": str(r["last_used_at"]) if r["last_used_at"] else None}
            for r in rows]


def verify(conn, org_id: int, token: Optional[str]) -> bool:
    if not token:
        return False
    row = conn.execute(text("SELECT token_hash FROM org_api_tokens WHERE org_id = :o"),
                       {"o": int(org_id)}).first()
    if not row or not hmac.compare_digest(str(row[0]), _hash(token)):
        return False
    try:
        conn.execute(text("UPDATE org_api_tokens SET last_used_at = CURRENT_TIMESTAMP WHERE org_id = :o"),
                     {"o": int(org_id)})
    except Exception:  # noqa: BLE001
        pass
    return True


def check_org_request(org_id) -> Optional[Any]:
    """
    Call at the top of a route that acts for ``org_id``. Returns None when the
    request may proceed, or a (response, 401) tuple to return.
    """
    m = mode()
    if m == "off":
        return None
    try:
        from services.admin_auth import is_admin_request
        if is_admin_request():
            return None
    except Exception:  # noqa: BLE001
        pass
    ok = False
    token = request.headers.get(HEADER)
    try:
        from db import get_engine
        with get_engine().begin() as conn:
            ok = org_id is not None and verify(conn, int(org_id), token)
    except Exception as e:  # noqa: BLE001  (table missing on an unmigrated DB)
        log.warning("org token check failed: %s", e)
    if ok:
        return None
    if m == "enforce":
        return jsonify(error="unauthorized",
                       message=f"This action needs the {HEADER} header for org {org_id}."), 401
    log.warning("org token missing or wrong for org %s on %s %s (ORG_TOKEN_MODE=warn, allowed)",
                org_id, request.method, request.path)
    return None
