"""
SQLite database layer for task persistence.
"""
import sqlite3
import os
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any
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
                name TEXT,
                completed_iterations INTEGER DEFAULT 0,
                original_n_iter INTEGER DEFAULT 0
            )
        """)

        # Index for efficient queue queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status_priority
            ON tasks (status, priority, created_at)
        """)

        # Bookmarks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                task_type TEXT NOT NULL,
                created_at TEXT,
                params TEXT,
                checkpoint TEXT,
                script_args TEXT
            )
        """)

        # Index for bookmark queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bookmarks_created
            ON bookmarks (created_at DESC)
        """)

        conn.commit()

        # Migration: add new columns if they don't exist
        self._migrate_db(conn)

    def _migrate_db(self, conn: sqlite3.Connection):
        """Add new columns to existing databases."""
        cursor = conn.cursor()

        # Check existing columns
        cursor.execute("PRAGMA table_info(tasks)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        # Add missing columns
        migrations = [
            ("completed_iterations", "INTEGER DEFAULT 0"),
            ("original_n_iter", "INTEGER DEFAULT 0"),
            ("requeued_task_id", "TEXT"),
            ("capture_format", "TEXT"),
        ]

        for col_name, col_type in migrations:
            if col_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}")
                    print(f"[TaskScheduler] Added column {col_name} to database")
                except sqlite3.OperationalError:
                    pass  # Column already exists

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

    def get_task(self, task_id: str, expand_metadata: bool = True) -> Optional[Task]:
        """
        Get a task by ID.

        Args:
            task_id: The task ID.
            expand_metadata: If True, fully deserialize script_args (for info view/execution).

        Returns:
            The task, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()

        if row:
            return Task.from_dict(dict(row), expand_metadata=expand_metadata)
        return None

    def get_all_tasks(self, include_completed: bool = True, expand_metadata: bool = False) -> List[Task]:
        """
        Get all tasks, ordered by priority and creation time.

        Args:
            include_completed: Whether to include completed/failed/cancelled tasks.
            expand_metadata: If True, fully deserialize script_args. Default False for list display.

        Returns:
            List of tasks.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if include_completed:
            # Active tasks (running/pending/paused) sorted by created_at DESC (newest first)
            # History tasks (completed/stopped/failed/cancelled) sorted by completed_at DESC
            cursor.execute("""
                SELECT * FROM tasks
                ORDER BY
                    CASE status
                        WHEN 'running' THEN 0
                        WHEN 'pending' THEN 1
                        WHEN 'paused' THEN 2
                        WHEN 'completed' THEN 3
                        WHEN 'stopped' THEN 4
                        WHEN 'failed' THEN 5
                        WHEN 'cancelled' THEN 6
                    END,
                    CASE
                        WHEN status IN ('completed', 'stopped', 'failed', 'cancelled') THEN completed_at
                        ELSE NULL
                    END DESC,
                    created_at DESC,
                    priority ASC
            """)
        else:
            cursor.execute("""
                SELECT * FROM tasks
                WHERE status IN ('pending', 'running')
                ORDER BY priority ASC, created_at ASC
            """)

        return [Task.from_dict(dict(row), expand_metadata=expand_metadata) for row in cursor.fetchall()]

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
            The next pending task with full metadata, or None if queue is empty.
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
            return Task.from_dict(dict(row), expand_metadata=True)
        return None

    def get_paused_task(self) -> Optional[Task]:
        """
        Get a paused task to resume.

        Returns:
            The paused task with full metadata, or None if no paused tasks.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM tasks
            WHERE status = 'paused'
            ORDER BY started_at DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        if row:
            return Task.from_dict(dict(row), expand_metadata=True)
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
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.STOPPED):
            updates["completed_at"] = datetime.now().isoformat()
        # PAUSED status doesn't set completed_at since it can be resumed

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
                WHERE status IN ('completed', 'failed', 'cancelled', 'stopped')
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
            "stopped": 0,
            "paused": 0,
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

    # =========================================================================
    # Bookmark Operations
    # =========================================================================

    def add_bookmark(self, bookmark_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new bookmark.

        Args:
            bookmark_data: Dictionary with bookmark fields (id, name, task_type, params, checkpoint, script_args)

        Returns:
            The added bookmark data.
        """
        import uuid

        conn = self._get_connection()
        cursor = conn.cursor()

        if 'id' not in bookmark_data:
            bookmark_data['id'] = str(uuid.uuid4())
        if 'created_at' not in bookmark_data:
            bookmark_data['created_at'] = datetime.now().isoformat()

        columns = ", ".join(bookmark_data.keys())
        placeholders = ", ".join("?" * len(bookmark_data))

        with self._lock:
            cursor.execute(
                f"INSERT INTO bookmarks ({columns}) VALUES ({placeholders})",
                list(bookmark_data.values())
            )
            conn.commit()

        return bookmark_data

    def get_bookmark(self, bookmark_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a bookmark by ID.

        Args:
            bookmark_id: The bookmark ID.

        Returns:
            The bookmark data, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,))
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    def get_all_bookmarks(self) -> List[Dict[str, Any]]:
        """
        Get all bookmarks, ordered by creation time (newest first).

        Returns:
            List of bookmark dictionaries.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM bookmarks
            ORDER BY created_at DESC
        """)

        return [dict(row) for row in cursor.fetchall()]

    def update_bookmark(self, bookmark_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a bookmark.

        Args:
            bookmark_id: The bookmark ID.
            updates: Dictionary of fields to update.

        Returns:
            True if updated, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())

        with self._lock:
            cursor.execute(
                f"UPDATE bookmarks SET {set_clause} WHERE id = ?",
                list(updates.values()) + [bookmark_id]
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_bookmark(self, bookmark_id: str) -> bool:
        """
        Delete a bookmark.

        Args:
            bookmark_id: The bookmark ID.

        Returns:
            True if deleted, False if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        with self._lock:
            cursor.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_bookmark_count(self) -> int:
        """
        Get the total number of bookmarks.

        Returns:
            Number of bookmarks.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM bookmarks")
        row = cursor.fetchone()
        return row['count'] if row else 0


# Global database instance
_db_instance: Optional[TaskDatabase] = None


def get_database() -> TaskDatabase:
    """Get the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = TaskDatabase()
    return _db_instance
