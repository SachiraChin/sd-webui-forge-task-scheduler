"""
SQLite database layer for task persistence.
"""
import sqlite3
import os
import threading
from typing import List, Optional
from pathlib import Path

from .models import Task, TaskStatus


class TaskDatabase:
    """
    SQLite database for storing scheduled tasks.
    Thread-safe with connection pooling per thread.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the database.

        Args:
            db_path: Path to the SQLite database file.
                     If None, uses default location in extension directory.
        """
        if db_path is None:
            # Default: store in extension directory
            ext_dir = Path(__file__).parent.parent
            db_path = str(ext_dir / "task_queue.db")

        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()

        # Initialize database schema
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    def _init_db(self):
        """Initialize the database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                created_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                params TEXT,
                checkpoint TEXT,
                script_args TEXT,
                result_images TEXT,
                result_info TEXT,
                error TEXT,
                name TEXT
            )
        """)

        # Index for efficient queue queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status_priority
            ON tasks (status, priority, created_at)
        """)

        conn.commit()

    def add_task(self, task: Task) -> Task:
        """
        Add a new task to the database.

        Args:
            task: The task to add.

        Returns:
            The added task (with any modifications).
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        data = task.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))

        with self._lock:
            cursor.execute(
                f"INSERT INTO tasks ({columns}) VALUES ({placeholders})",
                list(data.values())
            )
            conn.commit()

        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get a task by ID.

        Args:
            task_id: The task ID.

        Returns:
            The task, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()

        if row:
            return Task.from_dict(dict(row))
        return None

    def get_all_tasks(self, include_completed: bool = True) -> List[Task]:
        """
        Get all tasks, ordered by priority and creation time.

        Args:
            include_completed: Whether to include completed/failed/cancelled tasks.

        Returns:
            List of tasks.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if include_completed:
            cursor.execute("""
                SELECT * FROM tasks
                ORDER BY
                    CASE status
                        WHEN 'running' THEN 0
                        WHEN 'pending' THEN 1
                        WHEN 'completed' THEN 2
                        WHEN 'failed' THEN 3
                        WHEN 'cancelled' THEN 4
                    END,
                    priority ASC,
                    created_at ASC
            """)
        else:
            cursor.execute("""
                SELECT * FROM tasks
                WHERE status IN ('pending', 'running')
                ORDER BY priority ASC, created_at ASC
            """)

        return [Task.from_dict(dict(row)) for row in cursor.fetchall()]

    def get_pending_tasks(self) -> List[Task]:
        """
        Get all pending tasks, ordered by priority and creation time.

        Returns:
            List of pending tasks.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM tasks
            WHERE status = 'pending'
            ORDER BY priority ASC, created_at ASC
        """)

        return [Task.from_dict(dict(row)) for row in cursor.fetchall()]

    def get_next_pending_task(self) -> Optional[Task]:
        """
        Get the next pending task to execute.

        Returns:
            The next pending task, or None if queue is empty.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM tasks
            WHERE status = 'pending'
            ORDER BY priority ASC, created_at ASC
            LIMIT 1
        """)

        row = cursor.fetchone()
        if row:
            return Task.from_dict(dict(row))
        return None

    def update_task(self, task: Task) -> None:
        """
        Update an existing task.

        Args:
            task: The task with updated fields.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        data = task.to_dict()
        task_id = data.pop("id")
        set_clause = ", ".join(f"{k} = ?" for k in data.keys())

        with self._lock:
            cursor.execute(
                f"UPDATE tasks SET {set_clause} WHERE id = ?",
                list(data.values()) + [task_id]
            )
            conn.commit()

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        error: Optional[str] = None
    ) -> None:
        """
        Update a task's status.

        Args:
            task_id: The task ID.
            status: The new status.
            error: Optional error message (for failed status).
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        from datetime import datetime

        updates = {"status": status.value}

        if status == TaskStatus.RUNNING:
            updates["started_at"] = datetime.now().isoformat()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            updates["completed_at"] = datetime.now().isoformat()

        if error is not None:
            updates["error"] = error

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())

        with self._lock:
            cursor.execute(
                f"UPDATE tasks SET {set_clause} WHERE id = ?",
                list(updates.values()) + [task_id]
            )
            conn.commit()

    def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.

        Args:
            task_id: The task ID.

        Returns:
            True if the task was deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        with self._lock:
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def clear_completed(self) -> int:
        """
        Delete all completed, failed, and cancelled tasks.

        Returns:
            Number of tasks deleted.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        with self._lock:
            cursor.execute("""
                DELETE FROM tasks
                WHERE status IN ('completed', 'failed', 'cancelled')
            """)
            conn.commit()
            return cursor.rowcount

    def get_queue_stats(self) -> dict:
        """
        Get queue statistics.

        Returns:
            Dictionary with counts by status.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM tasks
            GROUP BY status
        """)

        stats = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "total": 0
        }

        for row in cursor.fetchall():
            stats[row["status"]] = row["count"]
            stats["total"] += row["count"]

        return stats

    def reorder_task(self, task_id: str, new_priority: int) -> None:
        """
        Change a task's priority.

        Args:
            task_id: The task ID.
            new_priority: The new priority value.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        with self._lock:
            cursor.execute(
                "UPDATE tasks SET priority = ? WHERE id = ?",
                (new_priority, task_id)
            )
            conn.commit()

    def close(self):
        """Close the database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


# Global database instance
_db_instance: Optional[TaskDatabase] = None


def get_database() -> TaskDatabase:
    """Get the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = TaskDatabase()
    return _db_instance
