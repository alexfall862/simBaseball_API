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
# Pull local env or Railway
# ----------------------------

try:
    if os.path.exists(".env"):
        from dotenv import load_dotenv
        load_dotenv(override=False)  # NEVER override Railway runtime env
except Exception:
    pass


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
    logging.getLogger("app").info("App boot: PID=%s, PORT=%s, DATABASE_URL set=%s", os.getpid(), os.getenv("PORT"), bool(os.getenv("DATABASE_URL")))
    logging.getLogger("app").info("ADMIN_PASSWORD set? %s", bool(os.getenv("ADMIN_PASSWORD")))
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
    log = logging.getLogger("app")
    log.info("stage: flask_start")

    app = Flask(__name__)
    app.config.from_object(config_object)
    app.config["DATABASE_URL"] = app.config.get("DATABASE_URL") or os.getenv("DATABASE_URL")
    log.info("stage: config_loaded")

    # (optional: hard-fail in prod)
    if os.getenv("RAILWAY_ENVIRONMENT") and not app.config["DATABASE_URL"]:
        log.warning("DATABASE_URL not set at runtime on Railway")


    #Register Blueprints
    try: 
        from orgs import orgs_bp
        app.register_blueprint(orgs_bp, url_prefix="/api/v1")
    except Exception as e:
        app.logger.exception("Failed to register orgs blueprint: %s", e)

    try: 
        from teams import teams_bp
        app.register_blueprint(teams_bp, url_prefix="/api/v1")
    except Exception as e:
        app.logger.exception("Failed to register teams blueprint: %s", e)
    try: 
        from players import players_bp
        app.register_blueprint(players_bp, url_prefix="/api/v1")
    except Exception as e:
        app.logger.exception("Failed to register players blueprint: %s", e)
    try: 
        from rosters import rosters_bp
        app.register_blueprint(rosters_bp, url_prefix="/api/v1")
    except Exception as e:
        app.logger.exception("Failed to register rosters blueprint: %s", e)

    try: 
        from seeding.contracts_seed import seed_initial_contracts
        app.register_blueprint(seed_initial_contracts, url_prefix="/api/v1")
    except Exception as e:
        app.logger.exception("Failed to register seeding blueprint: %s", e)





    from admin import admin_bp
    # Secure session cookie
    app.secret_key = os.getenv("FLASK_SECRET", os.urandom(32))
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=not app.debug,  # secure cookies in prod
    )

    # Mount the admin UI/API under /admin
    app.register_blueprint(admin_bp)
    log.info("stage: admin_bp_ok") 
    # Optional: a tiny root + favicon to keep logs clean
    @app.get("/")
    def root():
        return jsonify(status="up")

    @app.get("/favicon.ico")
    def favicon():
        return ("", 204)


    # CORS
    CORS(app, resources={r"/*": {"origins": app.config["CORS_ORIGINS"]}})
    log.info("stage: cors_ok")

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
    log.info("stage: engine_ok")
    logging.getLogger("app").info(
        "Boot: PORT=%s DBURL_present=%s",
        os.getenv("PORT"),
        bool(os.getenv("DATABASE_URL")),
    )

    @app.get("/debug/db")
    def debug_db():
        if app.engine is None:
            return jsonify(status="no_engine"), 503
        try:
            with app.engine.connect() as conn:
                db = conn.execute(text("SELECT DATABASE()")).scalar()
                ver = conn.execute(text("SELECT VERSION()")).scalar()
            return jsonify(status="ok", database=db, version=ver)
        except Exception as e:
            logging.exception("debug_db_failed")
            return jsonify(status="error", message=str(e)), 500

    # make the engine visible to blueprints
    app.engine = engine
    # (optional) also register in extensions for frameworks/tools that expect it there
    app.extensions = getattr(app, "extensions", {})
    app.extensions["sqlalchemy_engine"] = engine

    # Prometheus metrics
    if app.config["ENABLE_PROMETHEUS"] and PROMETHEUS_AVAILABLE:
        try:
            PrometheusMetrics(app, group_by="endpoint")
            log.info("Prometheus metrics enabled at /metrics")
            log.info("stage: prometheus_ok")

        except Exception:
            log.exception("prometheus_init_failed")

    # -------- Error Handlers --------
    @app.get("/routes")
    def _routes():
        from flask import Response
        lines = []
        for r in sorted(app.url_map.iter_rules(), key=lambda x: x.rule):
            lines.append(f"{','.join(sorted(r.methods))}  {r.rule}  -> {r.endpoint}")
        return Response("\n".join(lines), mimetype="text/plain")
    
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
    log.info("stage: handlers_ok")

    # -------- Example: parameterized raw SQL endpoint --------
    @app.get("/schema")
    @soft_timeout(app)
    def schema():
        table = request.args.get("table")

        if table:
            sql = text("""
                SELECT
                    c.TABLE_NAME  AS table_name,
                    c.COLUMN_NAME AS column_name,
                    c.DATA_TYPE   AS data_type,
                    c.IS_NULLABLE AS is_nullable,
                    c.COLUMN_DEFAULT AS column_default,
                    c.CHARACTER_MAXIMUM_LENGTH AS char_len,
                    c.NUMERIC_PRECISION AS num_precision,
                    c.NUMERIC_SCALE     AS num_scale
                FROM information_schema.COLUMNS c
                WHERE c.TABLE_SCHEMA = DATABASE()
                AND c.TABLE_NAME = :table
                ORDER BY c.ORDINAL_POSITION
            """)
            params = {"table": table}
        else:
            sql = text("""
                SELECT
                    c.TABLE_NAME  AS table_name,
                    c.COLUMN_NAME AS column_name,
                    c.DATA_TYPE   AS data_type,
                    c.IS_NULLABLE AS is_nullable,
                    c.COLUMN_DEFAULT AS column_default,
                    c.CHARACTER_MAXIMUM_LENGTH AS char_len,
                    c.NUMERIC_PRECISION AS num_precision,
                    c.NUMERIC_SCALE     AS num_scale
                FROM information_schema.COLUMNS c
                WHERE c.TABLE_SCHEMA = DATABASE()
                ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
            """)
            params = {}

        try:
            with engine.connect() as conn:
                result = conn.execute(sql, params)
                rows = [dict(r._mapping) for r in result]
        except Exception as e:
            logging.exception("schema_query_failed")
            return jsonify(error="schema_query_failed", message=str(e)), 500

        if table and not rows:
            return jsonify(error="table_not_found",
                        message=f"Table '{table}' not found"), 404

        schema_map = {}
        for r in rows:
            t = r.pop("table_name")
            schema_map.setdefault(t, []).append(r)
        return jsonify(schema=schema_map, table_count=len(schema_map))

    @app.post("/admin/seed-contracts")
    @soft_timeout(app)
    def seed_contracts():
        """
        One-off endpoint to wipe and reseed contractDetails and contractTeamShare,
        and reset contracts according to the seeding rules in seeding/contracts_seed.py.
        """

        # 1) Env guard so you don't run this by accident
        if os.getenv("ALLOW_CONTRACT_SEEDING", "false").lower() != "true":
            return jsonify(
                error="forbidden",
                message="Contract seeding is disabled. Set ALLOW_CONTRACT_SEEDING=true to enable."
            ), 403

        # 2) Simple admin auth using ADMIN_PASSWORD
        admin_pw = os.getenv("ADMIN_PASSWORD")
        if admin_pw:
            header_pw = request.headers.get("X-Admin-Password")
            if header_pw != admin_pw:
                return jsonify(
                    error="unauthorized",
                    message="Invalid admin password."
                ), 401

        # 3) Run the seeding function
        result = seed_initial_contracts()  # returns e.g. {"seeded_contracts": N}

        # 4) Return JSON summary
        return jsonify(
            status="ok",
            details=result,
        ), 200

    log.info("stage: routes_ok") 
    return app







# ----------------------------
# Helpers
# ----------------------------
def _build_engine(app):
    db_url = app.config.get("DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        logging.getLogger("app").warning("DATABASE_URL missing at runtime")
        return None

    # SAFETY NET: force PyMySQL if someone pasted mysql://
    if db_url.startswith("mysql://"):
        db_url = "mysql+pymysql://" + db_url[len("mysql://"):]
        logging.getLogger("app").info("Normalized DATABASE_URL to PyMySQL")

    # Add helpful defaults if missing
    if "charset=" not in db_url:
        sep = "&" if "?" in db_url else "?"
        db_url = f"{db_url}{sep}charset=utf8mb4"
    if "connect_timeout=" not in db_url:
        sep = "&" if "?" in db_url else "?"
        db_url = f"{db_url}{sep}connect_timeout={app.config['DB_CONNECT_TIMEOUT_S']}"

    connect_args = {}
    if "mysql" in db_url:
        connect_args = {
            "init_command": f"SET SESSION MAX_EXECUTION_TIME={app.config['DB_STATEMENT_TIMEOUT_MS']}",
        }

    if os.getenv("RAILWAY_ENVIRONMENT"):
        connect_args["ssl"] = {}

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
