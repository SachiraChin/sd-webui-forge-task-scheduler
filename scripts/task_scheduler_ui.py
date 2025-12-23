"""
Task Scheduler UI Integration for Stable Diffusion WebUI Forge.

This script:
1. Adds "Queue" button next to Generate buttons
2. Creates "Task Queue" tab for managing queued tasks
3. Supports two methods for capturing parameters:
   - gradio: Direct Gradio binding to UI components
   - interceptor: Intercepts StableDiffusionProcessing object (like Agent Scheduler)
"""
import gradio as gr
from typing import Optional
import json
import os
import sys

# Add parent directory to path for imports
ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ext_dir not in sys.path:
    sys.path.insert(0, ext_dir)

# Add scripts directory to path for method imports
scripts_dir = os.path.dirname(os.path.abspath(__file__))
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from modules import script_callbacks, shared, scripts
from task_scheduler.models import Task, TaskStatus, TaskType
from task_scheduler.queue_manager import get_queue_manager
from task_scheduler.executor import get_executor

# ============================================================================
# Method Configuration
# ============================================================================
# Choose which method to use for capturing generation parameters:
# - "gradio": Direct Gradio binding (captures UI component values)
# - "interceptor": Intercepts from StableDiffusionProcessing object (like Agent Scheduler)
QUEUE_METHOD = "interceptor"  # Change this to switch methods

# Import the selected method handler
if QUEUE_METHOD == "interceptor":
    from method_interceptor import setup_queue_buttons as method_setup_queue_buttons
    from method_interceptor import on_after_component as method_on_after_component
    print("[TaskScheduler] Using INTERCEPTOR method for parameter capture")
else:
    from method_gradio import setup_queue_buttons as method_setup_queue_buttons
    from method_gradio import on_after_component as method_on_after_component
    print("[TaskScheduler] Using GRADIO method for parameter capture")

# ============================================================================
# Global UI References (for Task Queue tab only)
# ============================================================================
_task_list_html: Optional[gr.HTML] = None
_queue_status_html: Optional[gr.HTML] = None


# ============================================================================
# Task Queue Tab Rendering Functions
# ============================================================================


def render_task_item(task: Task, index: int) -> str:
    """Render a single task item as HTML."""
    status_class = f"status-{task.status.value}"
    status_icon = {
        TaskStatus.PENDING: "⏳",
        TaskStatus.RUNNING: "🔄",
        TaskStatus.COMPLETED: "✅",
        TaskStatus.FAILED: "❌",
        TaskStatus.CANCELLED: "🚫"
    }.get(task.status, "")

    # Truncate prompt for display
    prompt = task.params.get("prompt", "")[:60]
    if len(task.params.get("prompt", "")) > 60:
        prompt += "..."

    # Escape HTML in prompt for title attribute
    prompt_escaped = task.params.get("prompt", "").replace('"', '&quot;').replace("'", "&#39;")

    checkpoint_short = task.get_short_checkpoint()

    # Build action buttons based on status
    actions_html = f'<button class="task-btn task-btn-info" onclick=\'taskSchedulerAction("info", "{task.id}")\' title="View details">ℹ️</button>'
    if task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
        actions_html += f'<button class="task-btn task-btn-retry" onclick=\'taskSchedulerAction("retry", "{task.id}")\' title="Retry this task">↻</button>'
    if task.status != TaskStatus.RUNNING:
        actions_html += f'<button class="task-btn task-btn-delete" onclick=\'taskSchedulerAction("delete", "{task.id}")\' title="Delete this task">🗑️</button>'

    return f"""
    <div class='task-item {status_class}' data-task-id='{task.id}'>
        <div class='task-index'>{index}</div>
        <div class='task-info'>
            <div class='task-type'>{task.task_type.value}</div>
            <div class='task-prompt' title="{prompt_escaped}">{prompt}</div>
            <div class='task-checkpoint'>Model: {checkpoint_short}</div>
        </div>
        <div class='task-status'><span class='status-badge'>{status_icon} {task.status.value}</span></div>
        <div class='task-actions'>{actions_html}</div>
    </div>
    """


def render_task_list() -> str:
    """Render the task list as HTML with separate Active and History sections."""
    queue_manager = get_queue_manager()
    tasks = queue_manager.get_all_tasks()

    if not tasks:
        return "<div class='task-empty'>No tasks in queue. Use the Queue button next to Generate to add tasks.</div>"

    # Separate active (pending/running) from history (completed/failed/cancelled)
    active_tasks = [t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
    history_tasks = [t for t in tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)]

    html_parts = []

    # Active Tasks Section
    html_parts.append("<div class='task-section task-section-active'>")
    html_parts.append("<h3 class='task-section-header'>Active Tasks</h3>")
    if active_tasks:
        html_parts.append("<div class='task-list'>")
        for i, task in enumerate(active_tasks, 1):
            html_parts.append(render_task_item(task, i))
        html_parts.append("</div>")
    else:
        html_parts.append("<div class='task-empty-small'>No active tasks</div>")
    html_parts.append("</div>")

    # History Section (collapsible)
    html_parts.append("<div class='task-section task-section-history'>")
    html_parts.append(f"<details class='task-history-details' {'open' if not active_tasks else ''}>")
    html_parts.append(f"<summary class='task-section-header task-history-summary'>History ({len(history_tasks)} tasks)</summary>")
    if history_tasks:
        html_parts.append("<div class='task-list task-list-history'>")
        for i, task in enumerate(history_tasks, 1):
            html_parts.append(render_task_item(task, i))
        html_parts.append("</div>")
    else:
        html_parts.append("<div class='task-empty-small'>No history</div>")
    html_parts.append("</details>")
    html_parts.append("</div>")

    return "".join(html_parts)


def render_queue_status() -> str:
    """Render queue status as HTML."""
    executor = get_executor()
    queue_manager = get_queue_manager()
    status = executor.get_status()
    stats = status["queue_stats"]

    # Determine status text and color
    if status["is_running"]:
        if status["is_paused"]:
            running_status = "Paused"
            status_class = "paused"
        elif stats['pending'] == 0 and stats['running'] == 0:
            running_status = "Idle (no pending tasks)"
            status_class = "idle"
        else:
            running_status = "Processing"
            status_class = "active"
    else:
        running_status = "Stopped"
        status_class = "inactive"

    current = ""
    if status["current_task"]:
        task_name = status['current_task'].get('name', '')
        if not task_name:
            # Try to get from params
            params = status['current_task'].get('params', {})
            if isinstance(params, str):
                import json
                try:
                    params = json.loads(params)
                except:
                    params = {}
            prompt = params.get('prompt', 'Unknown')[:30]
            task_name = f"{prompt}..."
        current = f"<br><small>Current: {task_name}</small>"

    return f"""
    <div class='queue-status {status_class}'>
        <span class='status-indicator {status_class}'></span>
        <div class='status-text'>
            <strong>Queue: {running_status}</strong>{current}
        </div>
        <div class='status-stats'>
            <span class='stat pending'>⏳ {stats['pending']} pending</span>
            <span class='stat running'>🔄 {stats['running']} running</span>
            <span class='stat completed'>✅ {stats['completed']} completed</span>
            <span class='stat failed'>❌ {stats['failed']} failed</span>
        </div>
    </div>
    """


def start_queue():
    """Start processing the queue."""
    print("[TaskScheduler] start_queue() called")
    executor = get_executor()
    queue_manager = get_queue_manager()
    stats = queue_manager.get_stats()

    print(f"[TaskScheduler] Queue stats: {stats}")
    print(f"[TaskScheduler] Executor is_running before: {executor.is_running}")

    # Check if there are pending tasks
    if stats['pending'] == 0:
        print("[TaskScheduler] No pending tasks")

    result = executor.start()
    print(f"[TaskScheduler] executor.start() returned: {result}")
    print(f"[TaskScheduler] Executor is_running after: {executor.is_running}")

    return render_queue_status(), render_task_list()


def stop_queue():
    """Stop processing the queue."""
    executor = get_executor()
    executor.stop()
    return render_queue_status(), render_task_list()


def pause_queue():
    """Pause/resume the queue."""
    executor = get_executor()
    if executor.is_paused:
        executor.resume()
    else:
        executor.pause()
    return render_queue_status(), render_task_list()


def clear_completed():
    """Clear completed/failed/cancelled tasks."""
    queue_manager = get_queue_manager()
    count = queue_manager.clear_completed()
    return render_queue_status(), render_task_list()


def refresh_queue():
    """Refresh the queue display."""
    return render_queue_status(), render_task_list()


def delete_task(task_id: str):
    """Delete a task from the queue."""
    queue_manager = get_queue_manager()
    queue_manager.delete_task(task_id)
    return render_queue_status(), render_task_list()


def create_task_queue_tab():
    """Create the Task Queue tab UI."""
    with gr.Blocks(analytics_enabled=False) as task_queue_tab:
        gr.HTML("<h2>Task Queue</h2>")
        gr.HTML("<p style='color: var(--body-text-color-subdued); margin-bottom: 10px;'>Use the Queue buttons next to Generate in txt2img/img2img tabs to add tasks.</p>")

        # Status display
        queue_status = gr.HTML(
            value=render_queue_status(),
            elem_id="task_queue_status"
        )

        # Control buttons
        with gr.Row():
            start_btn = gr.Button("▶️ Start Queue", variant="primary")
            stop_btn = gr.Button("⏹️ Stop Queue")
            pause_btn = gr.Button("⏸️ Pause/Resume")
            clear_btn = gr.Button("🗑️ Clear Completed")
            refresh_btn = gr.Button("🔄 Refresh")

        # Task list
        task_list = gr.HTML(
            value=render_task_list(),
            elem_id="task_queue_list"
        )

        # Hidden components for task actions
        task_id_input = gr.Textbox(visible=False, elem_id="task_action_id")
        task_action_output = gr.HTML(visible=False)

        # Button handlers
        start_btn.click(
            fn=start_queue,
            outputs=[queue_status, task_list]
        )

        stop_btn.click(
            fn=stop_queue,
            outputs=[queue_status, task_list]
        )

        pause_btn.click(
            fn=pause_queue,
            outputs=[queue_status, task_list]
        )

        clear_btn.click(
            fn=clear_completed,
            outputs=[queue_status, task_list]
        )

        refresh_btn.click(
            fn=refresh_queue,
            outputs=[queue_status, task_list]
        )

        # Task deletion handler
        task_id_input.change(
            fn=delete_task,
            inputs=[task_id_input],
            outputs=[queue_status, task_list]
        )

        # Store references for updates
        global _task_list_html, _queue_status_html
        _task_list_html = task_list
        _queue_status_html = queue_status

    return task_queue_tab


def on_ui_tabs():
    """Register the Task Queue tab."""
    task_queue_tab = create_task_queue_tab()
    return [(task_queue_tab, "Task Queue", "task_queue_tab")]


def on_after_component(component, **kwargs):
    """
    Delegate to the selected method handler.
    Detect Generate buttons and create Queue buttons next to them.
    """
    method_on_after_component(component, **kwargs)


def on_app_started(demo, app):
    """Called when the app starts - register API endpoints and setup Queue buttons."""
    from task_scheduler.api import setup_api
    setup_api(app)

    # Setup Queue buttons using the selected method
    try:
        method_setup_queue_buttons(demo)
    except Exception as e:
        print(f"[TaskScheduler] Error setting up Queue buttons: {e}")
        import traceback
        traceback.print_exc()

    print(f"[TaskScheduler] Extension loaded successfully (method: {QUEUE_METHOD})")


# CSS styles for the task queue
def add_style():
    """Add custom CSS styles."""
    return """
    <style>
    .task-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 10px;
    }
    .task-item {
        display: flex;
        align-items: center;
        padding: 10px;
        border-radius: 8px;
        background: var(--block-background-fill);
        border: 1px solid var(--border-color-primary);
    }
    .task-item.status-running {
        border-left: 4px solid #4CAF50;
    }
    .task-item.status-pending {
        border-left: 4px solid #2196F3;
    }
    .task-item.status-completed {
        border-left: 4px solid #8BC34A;
        opacity: 0.7;
    }
    .task-item.status-failed {
        border-left: 4px solid #f44336;
    }
    .task-item.status-cancelled {
        border-left: 4px solid #9E9E9E;
        opacity: 0.5;
    }
    .task-index {
        font-weight: bold;
        min-width: 30px;
        text-align: center;
    }
    .task-info {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin: 0 15px;
    }
    .task-type {
        font-size: 0.8em;
        color: var(--body-text-color-subdued);
        text-transform: uppercase;
    }
    .task-prompt {
        font-size: 0.95em;
    }
    .task-checkpoint {
        font-size: 0.8em;
        color: var(--body-text-color-subdued);
    }
    .task-status {
        min-width: 100px;
        text-align: center;
    }
    .task-actions button {
        background: transparent;
        border: none;
        cursor: pointer;
        font-size: 1.2em;
        padding: 5px;
    }
    .task-empty {
        text-align: center;
        padding: 40px;
        color: var(--body-text-color-subdued);
    }
    .queue-status {
        display: flex;
        align-items: center;
        gap: 15px;
        padding: 10px;
        background: var(--block-background-fill);
        border-radius: 8px;
        margin-bottom: 15px;
    }
    .status-indicator {
        width: 12px;
        height: 12px;
        border-radius: 50%;
    }
    .status-indicator.active {
        background: #4CAF50;
        animation: pulse 1.5s infinite;
    }
    .status-indicator.inactive {
        background: #9E9E9E;
    }
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    /* Task sections */
    .task-section {
        margin-bottom: 16px;
    }
    .task-section-header {
        font-size: 1em;
        font-weight: 600;
        margin: 0 0 8px 0;
        padding: 8px 12px;
        background: var(--block-background-fill);
        border-radius: 6px;
        color: var(--body-text-color);
    }
    .task-section-active .task-section-header {
        background: linear-gradient(135deg, rgba(33, 150, 243, 0.15), rgba(76, 175, 80, 0.15));
        border-left: 3px solid #2196F3;
    }
    .task-history-details {
        background: var(--block-background-fill);
        border-radius: 8px;
        overflow: hidden;
    }
    .task-history-summary {
        cursor: pointer;
        user-select: none;
        margin: 0;
        background: rgba(158, 158, 158, 0.1);
        border-left: 3px solid #9E9E9E;
    }
    .task-history-summary:hover {
        background: rgba(158, 158, 158, 0.2);
    }
    .task-list-history {
        padding-top: 8px;
    }
    .task-list-history .task-item {
        opacity: 0.8;
    }
    .task-empty-small {
        text-align: center;
        padding: 16px;
        color: var(--body-text-color-subdued);
        font-size: 0.9em;
    }
    </style>
    """


# Register callbacks
script_callbacks.on_ui_tabs(on_ui_tabs)
script_callbacks.on_after_component(on_after_component)
script_callbacks.on_app_started(on_app_started)
