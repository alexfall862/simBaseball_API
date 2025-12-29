# services/task_store.py
"""
Database-backed task store for background job tracking.

Provides persistent storage for long-running tasks across multiple workers.
Tasks are stored in the `background_tasks` table and automatically cleaned
up after a configurable TTL.
"""

import json
import time
import uuid
import logging
import gzip
from decimal import Decimal
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from enum import Enum


class DatabaseJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles database types like Decimal, datetime, etc."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            # Convert Decimal to float for JSON serialization
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        return super().default(obj)

from sqlalchemy import (
    MetaData, Table, Column, String, Text, Integer, Float,
    create_engine, select, delete, update, LargeBinary
)
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


# Table definition (will be created if it doesn't exist)
_metadata = MetaData()

background_tasks = Table(
    "background_tasks",
    _metadata,
    Column("id", String(32), primary_key=True),
    Column("status", String(20), nullable=False, default="pending"),
    Column("task_type", String(100), nullable=False),
    Column("progress", Integer, nullable=False, default=0),
    Column("total", Integer, nullable=False, default=0),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("metadata_json", Text, nullable=True),
    Column("result_json", LargeBinary, nullable=True),  # Compressed JSON
    Column("error", Text, nullable=True),
)


class DatabaseTaskStore:
    """
    Database-backed task store that works across multiple workers.

    Tasks are stored in the `background_tasks` table with compressed results
    to handle large payloads efficiently.
    """

    def __init__(self, engine, task_ttl_seconds: int = 3600):
        self._engine = engine
        self._ttl = task_ttl_seconds
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Create the background_tasks table if it doesn't exist."""
        try:
            _metadata.create_all(self._engine, tables=[background_tasks], checkfirst=True)
            logger.info("background_tasks table ready")
        except SQLAlchemyError as e:
            logger.error(f"Failed to create background_tasks table: {e}")
            raise

    def create_task(self, task_type: str, total: int = 0, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new pending task and return it."""
        task_id = str(uuid.uuid4())[:8]
        now = time.time()

        task_data = {
            "id": task_id,
            "status": TaskStatus.PENDING.value,
            "task_type": task_type,
            "progress": 0,
            "total": total,
            "created_at": now,
            "updated_at": now,
            "metadata_json": json.dumps(metadata or {}),
            "result_json": None,
            "error": None,
        }

        try:
            with self._engine.begin() as conn:
                self._cleanup_old_tasks(conn)
                conn.execute(background_tasks.insert().values(**task_data))

            logger.info(f"Created task {task_id} (type={task_type}, total={total})")
            return self._row_to_task(task_data)

        except SQLAlchemyError as e:
            logger.error(f"Failed to create task: {e}")
            raise

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a task by ID, or None if not found."""
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(background_tasks).where(background_tasks.c.id == task_id)
                ).mappings().first()

                if not row:
                    return None

                return self._row_to_task(dict(row))

        except SQLAlchemyError as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            return None

    def get_task_result_compressed(self, task_id: str) -> Optional[bytes]:
        """Get the raw compressed result for streaming/download."""
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    select(background_tasks.c.result_json, background_tasks.c.status)
                    .where(background_tasks.c.id == task_id)
                ).first()

                if not row or row[1] != TaskStatus.COMPLETE.value:
                    return None

                return row[0]

        except SQLAlchemyError as e:
            logger.error(f"Failed to get compressed result for task {task_id}: {e}")
            return None

    def set_running(self, task_id: str) -> bool:
        """Mark task as running."""
        return self._update_task(task_id, status=TaskStatus.RUNNING.value)

    def set_progress(self, task_id: str, progress: int) -> bool:
        """Update task progress."""
        return self._update_task(task_id, progress=progress)

    def set_complete(self, task_id: str, result: Any) -> bool:
        """Mark task as complete with result (compressed).

        Raises exceptions on failure so the caller can handle them appropriately.
        """
        # Compress the result JSON (use custom encoder for Decimal, datetime, etc.)
        # This is outside try/except so serialization errors bubble up to caller
        result_json = json.dumps(result, separators=(',', ':'), cls=DatabaseJSONEncoder)
        compressed = gzip.compress(result_json.encode('utf-8'))

        logger.info(
            f"Task {task_id} result: {len(result_json)} bytes -> "
            f"{len(compressed)} bytes compressed ({len(compressed)/len(result_json)*100:.1f}%)"
        )

        # Database update - let exceptions propagate to caller
        with self._engine.begin() as conn:
            db_result = conn.execute(
                update(background_tasks)
                .where(background_tasks.c.id == task_id)
                .values(
                    status=TaskStatus.COMPLETE.value,
                    result_json=compressed,
                    updated_at=time.time(),
                )
            )
            if db_result.rowcount == 0:
                raise ValueError(f"Task {task_id} not found in database")
            return True

    def set_failed(self, task_id: str, error: str) -> bool:
        """Mark task as failed with error message."""
        return self._update_task(task_id, status=TaskStatus.FAILED.value, error=error)

    def delete_task(self, task_id: str) -> bool:
        """Delete a task. Returns True if deleted."""
        try:
            with self._engine.begin() as conn:
                result = conn.execute(
                    delete(background_tasks).where(background_tasks.c.id == task_id)
                )
                return result.rowcount > 0

        except SQLAlchemyError as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            return False

    def list_tasks(self, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all tasks, optionally filtered by type."""
        try:
            with self._engine.connect() as conn:
                stmt = select(
                    background_tasks.c.id,
                    background_tasks.c.status,
                    background_tasks.c.task_type,
                    background_tasks.c.progress,
                    background_tasks.c.total,
                    background_tasks.c.created_at,
                    background_tasks.c.updated_at,
                    background_tasks.c.metadata_json,
                    background_tasks.c.error,
                    # Don't select result_json to avoid loading large data
                ).order_by(background_tasks.c.created_at.desc())

                if task_type:
                    stmt = stmt.where(background_tasks.c.task_type == task_type)

                rows = conn.execute(stmt).mappings().all()

                return [self._row_to_task(dict(row), include_result=False) for row in rows]

        except SQLAlchemyError as e:
            logger.error(f"Failed to list tasks: {e}")
            return []

    def _update_task(self, task_id: str, **values) -> bool:
        """Update task fields."""
        values["updated_at"] = time.time()

        try:
            with self._engine.begin() as conn:
                result = conn.execute(
                    update(background_tasks)
                    .where(background_tasks.c.id == task_id)
                    .values(**values)
                )
                return result.rowcount > 0

        except SQLAlchemyError as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            return False

    def _cleanup_old_tasks(self, conn):
        """Remove tasks older than TTL."""
        cutoff = time.time() - self._ttl

        try:
            result = conn.execute(
                delete(background_tasks).where(background_tasks.c.updated_at < cutoff)
            )
            if result.rowcount > 0:
                logger.info(f"Cleaned up {result.rowcount} expired tasks")

        except SQLAlchemyError as e:
            logger.warning(f"Failed to cleanup old tasks: {e}")

    def _row_to_task(self, row: Dict, include_result: bool = True) -> Dict[str, Any]:
        """Convert a database row to a task dict."""
        task = {
            "task_id": row["id"],
            "status": row["status"],
            "task_type": row["task_type"],
            "progress": row["progress"],
            "total": row["total"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": json.loads(row.get("metadata_json") or "{}"),
        }

        if row.get("error"):
            task["error"] = row["error"]

        if include_result and row.get("result_json") and row["status"] == TaskStatus.COMPLETE.value:
            try:
                decompressed = gzip.decompress(row["result_json"])
                task["result"] = json.loads(decompressed.decode('utf-8'))
            except Exception as e:
                logger.error(f"Failed to decompress result: {e}")
                task["result"] = None

        return task


# Global store instance (initialized lazily)
_task_store: Optional[DatabaseTaskStore] = None


def get_task_store() -> DatabaseTaskStore:
    """Get or create the global database task store instance."""
    global _task_store

    if _task_store is None:
        from db import get_engine
        engine = get_engine()
        _task_store = DatabaseTaskStore(engine)

    return _task_store
