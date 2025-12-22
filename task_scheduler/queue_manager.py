"""
Queue manager for task scheduling operations.
Provides high-level interface for queue operations.
"""
from typing import List, Optional, Callable
from datetime import datetime
import threading

from .models import Task, TaskStatus, TaskType
from .db import get_database, TaskDatabase


class QueueManager:
    """
    Manages the task queue with high-level operations.
    Thread-safe singleton pattern.
    """

    _instance: Optional["QueueManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._db: TaskDatabase = get_database()
        self._callbacks: List[Callable] = []
        self._initialized = True

    def add_task(
        self,
        task_type: TaskType,
        params: dict,
        checkpoint: str,
        script_args: list,
        name: str = ""
    ) -> Task:
        """
        Add a new task to the queue.

        Args:
            task_type: Type of generation (txt2img or img2img).
            params: Generation parameters dict.
            checkpoint: Checkpoint model name.
            script_args: Script/extension arguments.
            name: Optional display name.

        Returns:
            The created task.
        """
        task = Task(
            task_type=task_type,
            params=params,
            checkpoint=checkpoint,
            script_args=script_args,
            name=name,
            status=TaskStatus.PENDING,
            created_at=datetime.now()
        )

        self._db.add_task(task)
        self._notify_change("task_added", task)

        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._db.get_task(task_id)

    def get_all_tasks(self, include_completed: bool = True) -> List[Task]:
        """Get all tasks in the queue."""
        return self._db.get_all_tasks(include_completed)

    def get_pending_tasks(self) -> List[Task]:
        """Get all pending tasks."""
        return self._db.get_pending_tasks()

    def get_next_task(self) -> Optional[Task]:
        """Get the next task to execute."""
        return self._db.get_next_pending_task()

    def update_task(self, task: Task) -> None:
        """Update a task."""
        self._db.update_task(task)
        self._notify_change("task_updated", task)

    def set_task_running(self, task_id: str) -> None:
        """Mark a task as running."""
        self._db.update_task_status(task_id, TaskStatus.RUNNING)
        task = self._db.get_task(task_id)
        self._notify_change("task_started", task)

    def set_task_completed(
        self,
        task_id: str,
        result_images: List[str],
        result_info: str
    ) -> None:
        """Mark a task as completed with results."""
        task = self._db.get_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.result_images = result_images
            task.result_info = result_info
            self._db.update_task(task)
            self._notify_change("task_completed", task)

    def set_task_failed(self, task_id: str, error: str) -> None:
        """Mark a task as failed with error message."""
        self._db.update_task_status(task_id, TaskStatus.FAILED, error=error)
        task = self._db.get_task(task_id)
        self._notify_change("task_failed", task)

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a pending task.

        Returns:
            True if cancelled, False if task wasn't pending.
        """
        task = self._db.get_task(task_id)
        if task and task.status == TaskStatus.PENDING:
            self._db.update_task_status(task_id, TaskStatus.CANCELLED)
            self._notify_change("task_cancelled", task)
            return True
        return False

    def delete_task(self, task_id: str) -> bool:
        """Delete a task from the queue."""
        task = self._db.get_task(task_id)
        if task:
            result = self._db.delete_task(task_id)
            if result:
                self._notify_change("task_deleted", task)
            return result
        return False

    def clear_completed(self) -> int:
        """Clear all completed/failed/cancelled tasks."""
        count = self._db.clear_completed()
        if count > 0:
            self._notify_change("tasks_cleared", None)
        return count

    def reorder_task(self, task_id: str, new_priority: int) -> None:
        """Change a task's priority."""
        self._db.reorder_task(task_id, new_priority)
        task = self._db.get_task(task_id)
        self._notify_change("task_reordered", task)

    def move_task_up(self, task_id: str) -> None:
        """Move a task up in priority (decrease priority number)."""
        task = self._db.get_task(task_id)
        if task and task.priority > 0:
            self._db.reorder_task(task_id, task.priority - 1)
            self._notify_change("task_reordered", task)

    def move_task_down(self, task_id: str) -> None:
        """Move a task down in priority (increase priority number)."""
        task = self._db.get_task(task_id)
        if task:
            self._db.reorder_task(task_id, task.priority + 1)
            self._notify_change("task_reordered", task)

    def get_stats(self) -> dict:
        """Get queue statistics."""
        return self._db.get_queue_stats()

    def retry_task(self, task_id: str) -> Optional[Task]:
        """
        Retry a failed or cancelled task by creating a new pending copy.

        Returns:
            The new task, or None if original task not found.
        """
        original = self._db.get_task(task_id)
        if not original:
            return None

        # Create new task with same parameters
        new_task = Task(
            task_type=original.task_type,
            params=original.params,
            checkpoint=original.checkpoint,
            script_args=original.script_args,
            name=original.name,
            status=TaskStatus.PENDING,
            created_at=datetime.now()
        )

        self._db.add_task(new_task)
        self._notify_change("task_added", new_task)

        return new_task

    def register_callback(self, callback: Callable) -> None:
        """
        Register a callback for queue changes.

        Callback signature: callback(event: str, task: Optional[Task])
        Events: task_added, task_updated, task_started, task_completed,
                task_failed, task_cancelled, task_deleted, task_reordered,
                tasks_cleared
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable) -> None:
        """Unregister a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify_change(self, event: str, task: Optional[Task]) -> None:
        """Notify all registered callbacks of a change."""
        for callback in self._callbacks:
            try:
                callback(event, task)
            except Exception as e:
                print(f"[TaskScheduler] Callback error: {e}")


# Convenience function
def get_queue_manager() -> QueueManager:
    """Get the global queue manager instance."""
    return QueueManager()
