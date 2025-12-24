"""
Task data models for the scheduler.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
from enum import Enum
import json
import uuid

from .script_args_serializer import serialize_script_args, deserialize_script_args


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """Type of generation task."""
    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"


@dataclass
class Task:
    """
    Represents a queued generation task.

    Stores all parameters needed to reproduce the exact generation,
    including the checkpoint model, prompts, settings, and extension args.
    """
    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: TaskType = TaskType.TXT2IMG

    # Status tracking
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0  # Lower number = higher priority

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Generation parameters (stored as JSON-serializable dict)
    params: dict = field(default_factory=dict)

    # Checkpoint at time of queuing
    checkpoint: str = ""

    # Script/extension arguments (stored as JSON-serializable list)
    script_args: list = field(default_factory=list)

    # Results
    result_images: list = field(default_factory=list)  # Paths to saved images
    result_info: str = ""  # Generation info text
    error: Optional[str] = None  # Error message if failed

    # Display info (for UI)
    name: str = ""  # User-friendly name/description

    def to_dict(self) -> dict:
        """Convert task to a dictionary for database storage."""
        return {
            "id": self.id,
            "task_type": self.task_type.value if isinstance(self.task_type, TaskType) else self.task_type,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "priority": self.priority,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "params": json.dumps(self.params),
            "checkpoint": self.checkpoint,
            "script_args": serialize_script_args(self.script_args),
            "result_images": json.dumps(self.result_images),
            "result_info": self.result_info,
            "error": self.error,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: dict, expand_metadata: bool = True) -> "Task":
        """
        Create a Task from a database row dictionary.

        Args:
            data: Dictionary from database row
            expand_metadata: If True, fully deserialize script_args (for info view/execution).
                           If False, keep script_args as empty list (for task list display).
        """
        # Only deserialize script_args when needed (info view, task execution)
        if expand_metadata:
            script_args = deserialize_script_args(data.get("script_args", ""))
        else:
            script_args = []

        return cls(
            id=data["id"],
            task_type=TaskType(data["task_type"]) if data.get("task_type") else TaskType.TXT2IMG,
            status=TaskStatus(data["status"]) if data.get("status") else TaskStatus.PENDING,
            priority=data.get("priority", 0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            params=json.loads(data["params"]) if data.get("params") else {},
            checkpoint=data.get("checkpoint", ""),
            script_args=script_args,
            result_images=json.loads(data["result_images"]) if data.get("result_images") else [],
            result_info=data.get("result_info", ""),
            error=data.get("error"),
            name=data.get("name", ""),
        )

    def get_display_name(self) -> str:
        """Get a display name for the task."""
        if self.name:
            return self.name

        # Generate from prompt
        prompt = self.params.get("prompt", "")
        if prompt:
            # Truncate long prompts
            if len(prompt) > 50:
                return f"{self.task_type.value}: {prompt[:47]}..."
            return f"{self.task_type.value}: {prompt}"

        return f"{self.task_type.value} task"

    def get_short_checkpoint(self) -> str:
        """Get a shortened checkpoint name for display."""
        if not self.checkpoint:
            return "Unknown"
        # Remove hash if present: "model_name [hash]" -> "model_name"
        return self.checkpoint.split(" [")[0]
