# SD WebUI Forge Task Scheduler - Architecture Document

## Overview

A task scheduling extension for Stable Diffusion WebUI Forge that allows users to queue generation tasks and run them later, providing flexibility for managing large batches without waiting for each to complete.

## Problem Statement

Forge's current queue is primitive - tasks must be started immediately. Users cannot:
- Queue multiple tasks with different configurations
- Stage tasks and run them later
- Manage a backlog of generation jobs

## Solution Architecture

### Core Components

```
sd-webui-forge-task-scheduler/
├── scripts/
│   └── task_scheduler.py      # Main extension script (UI + callbacks)
├── task_scheduler/
│   ├── __init__.py
│   ├── db.py                  # SQLite database layer
│   ├── models.py              # Task data models
│   ├── queue_manager.py       # Queue operations
│   ├── executor.py            # Task execution engine
│   └── api.py                 # FastAPI endpoints
├── javascript/
│   └── task_scheduler.js      # Frontend UI enhancements
├── style.css                  # Custom styling
├── install.py                 # Installation dependencies
└── README.md
```

### 1. Data Layer (db.py + models.py)

**Database**: SQLite (persistent storage in extension directory)

**Task Schema**:
```python
@dataclass
class Task:
    id: str                    # UUID
    task_type: str             # "txt2img" | "img2img"
    status: str                # "pending" | "running" | "completed" | "failed" | "cancelled"
    priority: int              # For ordering (default: 0, lower runs first)
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    # Generation parameters (JSON serialized)
    params: dict               # All txt2img/img2img parameters
    checkpoint: str            # Model name at time of queuing

    # Script/extension state (JSON serialized)
    script_args: dict          # All extension arguments

    # Results
    result_images: list[str]   # Paths to generated images
    result_info: str           # Generation info text
    error: str | None          # Error message if failed
```

### 2. Parameter Capture

**Challenge**: Capture ALL UI state including:
- Basic parameters (prompt, negative prompt, size, steps, CFG, sampler, etc.)
- HiRes fix settings
- Current checkpoint model
- All extension/script arguments (ControlNet, ADetailer, etc.)

**Solution**: Use the same parameter structure as txt2img/img2img functions:

```python
def capture_txt2img_params(component_values) -> dict:
    """
    Capture all parameters from UI components.
    Matches txt2img_create_processing signature in modules/txt2img.py
    """
    return {
        "prompt": ...,
        "negative_prompt": ...,
        "prompt_styles": ...,
        "n_iter": ...,
        "batch_size": ...,
        # ... all parameters
        "checkpoint": shared.opts.sd_model_checkpoint,
        "script_args": [...],  # All extension arguments
    }
```

### 3. Queue Manager (queue_manager.py)

```python
class QueueManager:
    def add_task(self, task_type: str, params: dict) -> Task
    def get_pending_tasks(self) -> list[Task]
    def get_task(self, task_id: str) -> Task
    def update_task_status(self, task_id: str, status: str)
    def delete_task(self, task_id: str)
    def reorder_task(self, task_id: str, new_priority: int)
    def clear_completed(self)
```

### 4. Task Executor (executor.py)

**Execution Strategy**:
1. Background thread monitors queue state
2. When queue is "running" and no task is active, picks next pending task
3. Loads required checkpoint if different from current
4. Reconstructs processing object from saved parameters
5. Calls `process_images()` via Forge's main thread mechanism
6. Saves results and updates task status

```python
class TaskExecutor:
    def __init__(self, queue_manager: QueueManager):
        self.queue = queue_manager
        self.is_running = False
        self.current_task: Task | None = None
        self._thread: Thread | None = None

    def start(self):
        """Start processing queue"""
        self.is_running = True
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop after current task completes"""
        self.is_running = False

    def _run_loop(self):
        while self.is_running:
            if shared.state.job_count > 0:
                time.sleep(1)  # Wait if generation in progress
                continue

            task = self.queue.get_next_pending()
            if task:
                self._execute_task(task)
            else:
                time.sleep(0.5)  # No tasks, wait

    def _execute_task(self, task: Task):
        """Execute a single task using Forge's generation pipeline"""
        # 1. Switch checkpoint if needed
        # 2. Reconstruct StableDiffusionProcessing object
        # 3. Run via main_thread.run_and_wait_result
        # 4. Save results
```

**Critical**: Must use `modules_forge.main_thread.run_and_wait_result()` to ensure proper GPU access and thread safety.

### 5. UI Integration (scripts/task_scheduler.py)

**Adding Queue Button**:
Use `on_after_component` callback to inject Queue button next to Generate:

```python
def on_after_component(component, **kwargs):
    elem_id = kwargs.get("elem_id", "")

    # Inject after Generate button
    if elem_id in ["txt2img_generate", "img2img_generate"]:
        with gr.Row():
            queue_btn = gr.Button("Queue", variant="secondary")
```

**Task Queue Tab**:
Use `on_ui_tabs` callback to add new tab:

```python
def on_ui_tabs():
    with gr.Blocks() as scheduler_tab:
        with gr.Row():
            start_btn = gr.Button("Start Queue")
            stop_btn = gr.Button("Stop Queue")
            clear_btn = gr.Button("Clear Completed")

        queue_status = gr.HTML()
        task_list = gr.Dataframe(...)  # Task display

        # Task detail view
        with gr.Row():
            task_preview = gr.Gallery()
            task_info = gr.Textbox()

    return [(scheduler_tab, "Task Queue", "task_queue_tab")]
```

### 6. API Endpoints (api.py)

Register FastAPI routes for external access:

```python
def setup_api(app: FastAPI):
    @app.get("/task-scheduler/queue")
    def get_queue(): ...

    @app.post("/task-scheduler/queue/txt2img")
    def queue_txt2img(params: dict): ...

    @app.post("/task-scheduler/queue/{task_id}/cancel")
    def cancel_task(task_id: str): ...

    @app.post("/task-scheduler/start")
    def start_queue(): ...

    @app.post("/task-scheduler/stop")
    def stop_queue(): ...
```

### 7. Frontend JavaScript (task_scheduler.js)

- Auto-refresh task list while queue is running
- Task reordering via drag-and-drop
- Inline task editing
- Progress display during execution

## Key Implementation Details

### Parameter Serialization

For img2img, init images must be handled specially:
- Save images to temp directory
- Store paths in task params
- Reload on execution

### Checkpoint Switching

```python
def switch_checkpoint(checkpoint_name: str):
    from modules import sd_models
    checkpoint_info = sd_models.get_closet_checkpoint_match(checkpoint_name)
    if checkpoint_info and shared.opts.sd_model_checkpoint != checkpoint_info.title:
        sd_models.reload_model_weights(info=checkpoint_info)
```

### Script Arguments Handling

Extensions store args in specific indices. Must capture and restore:
```python
# Capture: Store script_args as-is (already serializable for most)
# Restore: Pass back to scripts.scripts_txt2img.run(p, *script_args)
```

### Error Handling

- Wrap execution in try/except
- Log errors to task record
- Continue to next task on failure
- Provide retry mechanism for failed tasks

## Browser Tab Independence

**Phase 1 (Initial)**: Requires browser tab open
- Queue state in memory
- Polling for updates via Gradio

**Phase 2 (Enhancement)**: Works with browser closed
- Full state in SQLite
- Background thread independent of Gradio
- API endpoints for status checks

## UI Mockup

```
┌─────────────────────────────────────────────────────────────┐
│ [txt2img] [img2img] [Extras] [PNG Info] [Task Queue]       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Queue Status: Running (2/5 tasks)                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ [▶ Start] [⏹ Stop] [🗑 Clear Completed] [↻ Refresh] │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌───┬────────────────┬──────────┬──────────┬─────────┐   │
│  │ # │ Task           │ Model    │ Status   │ Actions │   │
│  ├───┼────────────────┼──────────┼──────────┼─────────┤   │
│  │ 1 │ txt2img: "a... │ sdxl_1.0 │ Running  │ [⏹]     │   │
│  │ 2 │ txt2img: "b... │ sdxl_1.0 │ Pending  │ [▲▼] [✕]│   │
│  │ 3 │ img2img: "c... │ sd15     │ Pending  │ [▲▼] [✕]│   │
│  │ 4 │ txt2img: "d... │ sdxl_1.0 │ Completed│ [↻] [✕] │   │
│  │ 5 │ txt2img: "e... │ sdxl_1.0 │ Failed   │ [↻] [✕] │   │
│  └───┴────────────────┴──────────┴──────────┴─────────┘   │
│                                                             │
│  Selected Task Details:                                     │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Prompt: "a beautiful landscape..."                   │   │
│  │ Negative: "blurry, low quality"                     │   │
│  │ Steps: 20 | CFG: 7 | Size: 1024x1024                │   │
│  │ Sampler: Euler a                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  [Preview Gallery]                                          │
│  ┌───────┬───────┬───────┬───────┐                         │
│  │  img1 │  img2 │  img3 │  img4 │                         │
│  └───────┴───────┴───────┴───────┘                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Dependencies

- Python standard library (sqlite3, threading, uuid, json, dataclasses)
- Gradio (already in Forge)
- FastAPI (already in Forge)

No additional pip packages required.

## Implementation Phases

### Phase 1: Core Functionality
1. Database setup
2. Task model and queue manager
3. Parameter capture for txt2img
4. Queue button injection
5. Task Queue tab with basic list
6. Simple executor (no checkpoint switching)

### Phase 2: Full Features
1. img2img support with image handling
2. Checkpoint switching
3. Task reordering and priority
4. Task editing
5. Error handling and retry

### Phase 3: Polish
1. API endpoints
2. JavaScript enhancements
3. Progress tracking
4. Settings page options
5. Browser-closed operation

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Extension args not serializable | Use pickle for complex objects, fallback to defaults |
| Checkpoint switch during queue | Lock queue during manual operations |
| Memory leaks from long runs | Periodic cleanup, explicit gc.collect() |
| Race conditions | Use threading locks, queue operations |
| GPU contention | Use main_thread mechanism, check state.job_count |

## Testing Strategy

1. Unit tests for queue manager
2. Integration tests for parameter capture
3. Manual testing for UI interactions
4. Long-running stability tests
