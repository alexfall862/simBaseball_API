# services/task_store.py
"""
In-memory task store for background job tracking.

Provides a simple way to track long-running tasks with status, progress,
and results. Tasks are stored in memory and automatically cleaned up
after a configurable TTL.

For production with multiple workers, consider replacing with Redis.
"""

import threading
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    status: TaskStatus
    task_type: str
    created_at: float
    updated_at: float
    progress: int = 0
    total: int = 0
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_result: bool = True) -> Dict[str, Any]:
        """Convert task to JSON-serializable dict."""
        d = {
            "task_id": self.id,
            "status": self.status.value,
            "task_type": self.task_type,
            "progress": self.progress,
            "total": self.total,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

        if self.status == TaskStatus.FAILED:
            d["error"] = self.error

        if include_result and self.status == TaskStatus.COMPLETE:
            d["result"] = self.result

        return d


class TaskStore:
    """
    Thread-safe in-memory task store.

    Tasks are automatically cleaned up after `task_ttl_seconds` (default: 1 hour).
    """

    def __init__(self, task_ttl_seconds: int = 3600):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.RLock()
        self._ttl = task_ttl_seconds

    def create_task(self, task_type: str, total: int = 0, metadata: Optional[Dict] = None) -> Task:
        """Create a new pending task and return it."""
        task_id = str(uuid.uuid4())[:8]  # Short ID for convenience
        now = time.time()

        task = Task(
            id=task_id,
            status=TaskStatus.PENDING,
            task_type=task_type,
            created_at=now,
            updated_at=now,
            total=total,
            metadata=metadata or {},
        )

        with self._lock:
            self._cleanup_old_tasks()
            self._tasks[task_id] = task

        logger.info(f"Created task {task_id} (type={task_type}, total={total})")
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID, or None if not found."""
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> Optional[Task]:
        """Update task fields. Returns updated task or None if not found."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = progress
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error

            task.updated_at = time.time()
            return task

    def set_running(self, task_id: str) -> Optional[Task]:
        """Mark task as running."""
        return self.update_task(task_id, status=TaskStatus.RUNNING)

    def set_progress(self, task_id: str, progress: int) -> Optional[Task]:
        """Update task progress."""
        return self.update_task(task_id, progress=progress)

    def set_complete(self, task_id: str, result: Any) -> Optional[Task]:
        """Mark task as complete with result."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.COMPLETE
                task.result = result
                task.progress = task.total
                task.updated_at = time.time()
        return task

    def set_failed(self, task_id: str, error: str) -> Optional[Task]:
        """Mark task as failed with error message."""
        return self.update_task(task_id, status=TaskStatus.FAILED, error=error)

    def delete_task(self, task_id: str) -> bool:
        """Delete a task. Returns True if deleted, False if not found."""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    def list_tasks(self, task_type: Optional[str] = None) -> list[Task]:
        """List all tasks, optionally filtered by type."""
        with self._lock:
            tasks = list(self._tasks.values())

        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]

        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def _cleanup_old_tasks(self):
        """Remove tasks older than TTL. Called internally with lock held."""
        now = time.time()
        cutoff = now - self._ttl

        expired = [
            tid for tid, task in self._tasks.items()
            if task.updated_at < cutoff
        ]

        for tid in expired:
            del self._tasks[tid]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired tasks")


# Global task store instance
_task_store: Optional[TaskStore] = None


def get_task_store() -> TaskStore:
    """Get or create the global task store instance."""
    global _task_store
    if _task_store is None:
        _task_store = TaskStore()
    return _task_store
