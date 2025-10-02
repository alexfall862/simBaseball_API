# db.py
import os
from sqlalchemy import create_engine


_engine = None

def get_engine():
    global _engine
    if _engine is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is not set")
        # Ensure url uses the sqlalchemy+driver scheme; user confirmed mysql+pymysql is already used
        _engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=1800, # recycle connections every 30m
        pool_size=5,
        max_overflow=5,
        future=True,
        )
    return _engine