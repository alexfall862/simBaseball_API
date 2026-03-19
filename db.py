# db.py
import os
import logging

from sqlalchemy import create_engine, event

logger = logging.getLogger(__name__)

_engine = None

def get_engine():
    global _engine
    if _engine is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is not set")

        # Socket-level timeouts prevent indefinite hangs when MySQL is unresponsive.
        # These are distinct from MAX_EXECUTION_TIME (query-level, used by app.py
        # for HTTP-serving connections).  60s is conservative — the largest
        # operation is a bulk upsert of ~300 rows which normally completes in <5s.
        connect_args = {
            "read_timeout": 60,
            "write_timeout": 60,
        }
        if os.getenv("RAILWAY_ENVIRONMENT"):
            connect_args["ssl"] = {}

        _engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=280,  # recycle before Railway proxy drops idle conns (~5min)
            pool_size=10,
            max_overflow=10,
            future=True,
            connect_args=connect_args,
        )

        # Belt-and-suspenders: ensure every connection checked out from the pool
        # has FOREIGN_KEY_CHECKS = 1.  The stat_accumulator temporarily disables
        # FK checks during bulk writes and re-enables in a finally block, but if
        # the connection is lost between disable and re-enable, the next consumer
        # would inherit FK checks OFF.
        @event.listens_for(_engine, "checkout")
        def _reset_fk_checks(dbapi_conn, connection_record, connection_proxy):
            try:
                cursor = dbapi_conn.cursor()
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                cursor.close()
            except Exception:
                logger.debug("db: failed to reset FK checks on checkout (connection may be stale)")

    return _engine
