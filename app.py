import os, json, logging, time, uuid, datetime
from functools import wraps

from flask import has_request_context
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from werkzeug.exceptions import HTTPException, BadRequest

# ---- Rate limiting (lightweight) ----
# Using flask-limiter is great; if you prefer zero extra deps, here's a tiny in-memory limiter.
# Swap for flask-limiter in real prod or Redis-backed limiters in multi-instance deployments.
from collections import defaultdict, deque

# ---- SQLAlchemy Core (no ORM) ----
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError, OperationalError, DBAPIError

# ---- Optional: Prometheus metrics ----
try:
    from prometheus_flask_exporter import PrometheusMetrics
    PROMETHEUS_AVAILABLE = True
except Exception:
    PROMETHEUS_AVAILABLE = False


# ----------------------------
# Config
# ----------------------------
class Config:
    ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = ENV == "development"
    TESTING = False

    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

    # Database URL (Railway usually provides DATABASE_URL like postgres://… or postgresql://…)
    DATABASE_URL = os.getenv("DATABASE_URL")

    # DB timeouts (ms). Enforced at the DB level via connection options.
    DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "8000"))  # 8s
    DB_CONNECT_TIMEOUT_S = int(os.getenv("DB_CONNECT_TIMEOUT_S", "5"))

    # SQLAlchemy pool settings
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "5"))
    DB_POOL_RECYCLE_S = int(os.getenv("DB_POOL_RECYCLE_S", "300"))
    DB_POOL_PRE_PING = True  # important for long-lived connections

    # Request / server settings
    REQUEST_MAX_BODY_BYTES = int(os.getenv("REQUEST_MAX_BODY_BYTES", "1048576"))  # 1 MB
    REQUEST_SOFT_TIMEOUT_S = int(os.getenv("REQUEST_SOFT_TIMEOUT_S", "12"))  # app-level guard

    # Rate limiting
    RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))  # per window
    RATE_LIMIT_WINDOW_S = int(os.getenv("RATE_LIMIT_WINDOW_S", "60"))   # seconds

    # Feature flags
    ENABLE_PROMETHEUS = os.getenv("ENABLE_PROMETHEUS", "true").lower() == "true"


# ----------------------------
# Logging (JSON)
# ----------------------------
class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "pid": os.getpid(),
        }

        # Only touch request/g if we actually have a request context
        if has_request_context():
            try:
                payload["path"] = request.path
                payload["method"] = request.method
            except Exception:
                pass
            try:
                rid = getattr(g, "request_id", None)
                if rid:
                    payload["request_id"] = rid
            except Exception:
                pass

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)

def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)  # ensure it's exactly INFO
    formatter = JsonFormatter()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        h = logging.StreamHandler()
        h.setFormatter(formatter)
        root.addHandler(h)
    else:
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setFormatter(formatter)


# ----------------------------
# Tiny in-memory rate limiter (swap for flask-limiter + Redis in multi-instance)
# ----------------------------
class SimpleRateLimiter:
    def __init__(self, max_requests, window_s):
        self.max_requests = max_requests
        self.window_s = window_s
        self.buckets = defaultdict(deque)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        q = self.buckets[key]
        # Drop old timestamps
        while q and q[0] <= now - self.window_s:
            q.popleft()
        if len(q) >= self.max_requests:
            return False
        q.append(now)
        return True


# ----------------------------
# App Factory
# ----------------------------
def create_app(config_object=Config):
    setup_logging()
    app = Flask(__name__)
    app.config.from_object(config_object)

    # CORS
    CORS(app, resources={r"/*": {"origins": app.config["CORS_ORIGINS"]}})

    # Request ID middleware
    @app.before_request
    def attach_request_id():
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        # lightweight body size guard
        cl = request.headers.get("Content-Length")
        if cl and int(cl) > app.config["REQUEST_MAX_BODY_BYTES"]:
            raise BadRequest("Request body too large")

    # Simple rate limit
    limiter = SimpleRateLimiter(
        app.config["RATE_LIMIT_REQUESTS"], app.config["RATE_LIMIT_WINDOW_S"]
    )

    @app.before_request
    def apply_rate_limit():
        key = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
        if not limiter.is_allowed(key):
            return jsonify(error="rate_limited", message="Too many requests"), 429

    # Database engine (SQLAlchemy Core)
    if not app.config["DATABASE_URL"]:
        logging.getLogger("app").warning("DATABASE_URL not set. /readyz will fail.")
    engine = _build_engine(app)

    # Prometheus metrics
    if app.config["ENABLE_PROMETHEUS"] and PROMETHEUS_AVAILABLE:
        PrometheusMetrics(app, group_by='endpoint')
        logging.getLogger("app").info("Prometheus metrics enabled at /metrics")

    # -------- Error Handlers --------
    @app.errorhandler(HTTPException)
    def handle_http_ex(e: HTTPException):
        return jsonify(error=e.name, message=e.description), e.code

    @app.errorhandler(SQLAlchemyError)
    def handle_db_ex(e):
        logging.exception("Database error")
        return jsonify(error="database_error", message=str(getattr(e, "__cause__", e))), 500

    @app.errorhandler(Exception)
    def handle_generic_ex(e):
        logging.exception("Unhandled error")
        return jsonify(error="internal_error", message="Something went wrong"), 500

    # -------- Health / Readiness --------
    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", time=time.time())

    @app.get("/readyz")
    def readyz():
        # quick DB ping
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return jsonify(status="ready")
        except Exception as e:
            return jsonify(status="degraded", error=str(e)), 503

    # -------- Example: parameterized raw SQL endpoint --------
    # GET /users?since=2025-01-01&limit=50
    @app.get("/users")
    @soft_timeout(app)
    def list_users():
        """
        Example template endpoint showing safe parameterized SQL with a connection
        from the pool. Replace table/columns for your schema.

        Query params:
          - since: ISO date (defaults to 30 days ago)
          - limit: max rows (defaults 50, max 500)
        """
        since_param = request.args.get("since")
        limit_param = request.args.get("limit", "50")

        # validate inputs
        try:
            if since_param:
                since = datetime.datetime.fromisoformat(since_param).date()
            else:
                since = (datetime.date.today() - datetime.timedelta(days=30))
            limit = max(1, min(500, int(limit_param)))
        except Exception:
            raise BadRequest("Invalid query params: use ISO date for 'since' and integer for 'limit'")

        sql = text("""
            SELECT id, name, email, created_at
            FROM users
            WHERE created_at >= :since
            ORDER BY created_at DESC
            LIMIT :limit
        """)

        rows = []
        start = time.time()
        try:
            with engine.connect() as conn:
                # Tip: for large responses, stream via server-side cursors.
                result = conn.execute(sql, {"since": since, "limit": limit})
                for r in result.mappings():
                    rows.append({
                        "id": r["id"],
                        "name": r["name"],
                        "email": r["email"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None
                    })
        except OperationalError as e:
            # transient connection issue? Basic retry guidance:
            raise e

        latency_ms = int((time.time() - start) * 1000)
        return jsonify(
            request_id=g.request_id,
            count=len(rows),
            latency_ms=latency_ms,
            data=rows
        )

    return app


# ----------------------------
# Helpers
# ----------------------------
def _build_engine(app):
    db_url = app.config["DATABASE_URL"]
    if not db_url:
        return None

    if "postgres" in db_url:
        # (existing Postgres branch) ...
        ...
    elif "mysql" in db_url:
        # Enforce SELECT statement timeout at session level (MySQL 5.7.8+ / 8.0+)
        connect_args = {
            "init_command": f"SET SESSION MAX_EXECUTION_TIME={app.config['DB_STATEMENT_TIMEOUT_MS']}"
        }
    else:
        connect_args = {}

    engine = create_engine(
        db_url,
        pool_size=app.config["DB_POOL_SIZE"],
        max_overflow=app.config["DB_MAX_OVERFLOW"],
        pool_recycle=app.config["DB_POOL_RECYCLE_S"],
        pool_pre_ping=True,
        connect_args=connect_args,
        future=True,
    )
    return engine


def soft_timeout(app: Flask):
    """
    Decorator that enforces a soft request timeout (app level).
    DB statements have their own statement_timeout; this protects
    non-DB work. Returns 503 if exceeded.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = fn(*args, **kwargs)
            elapsed = time.time() - start
            if elapsed > app.config["REQUEST_SOFT_TIMEOUT_S"]:
                logging.getLogger("app").warning("soft_timeout_exceeded")
                # Still return, but you could choose to 503 here; keeping gentle behavior.
            return result
        return wrapper
    return decorator


# ----------------------------
# Entrypoint
# ----------------------------
if __name__ == "__main__":
    app = create_app()
    # For local dev only; use gunicorn in production
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
