"""
Task Scheduler UI Integration for Stable Diffusion WebUI Forge.

This script:
1. Adds "Queue" button next to Generate buttons
2. Creates "Task Queue" tab for managing queued tasks
3. Captures all generation parameters when queuing
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

from modules import script_callbacks, shared, scripts
from task_scheduler.models import Task, TaskStatus, TaskType
from task_scheduler.queue_manager import get_queue_manager
from task_scheduler.executor import get_executor


# Global references to UI components for updates
_txt2img_queue_btn: Optional[gr.Button] = None
_img2img_queue_btn: Optional[gr.Button] = None
_task_list_html: Optional[gr.HTML] = None
_queue_status_html: Optional[gr.HTML] = None


def get_current_checkpoint() -> str:
    """Get the currently selected checkpoint model."""
    try:
        return shared.opts.sd_model_checkpoint or ""
    except Exception:
        return ""


def queue_txt2img_task(
    prompt, negative_prompt, prompt_styles,
    n_iter, batch_size, cfg_scale, distilled_cfg_scale,
    height, width,
    enable_hr, denoising_strength, hr_scale, hr_upscaler,
    hr_second_pass_steps, hr_resize_x, hr_resize_y,
    hr_checkpoint_name, hr_additional_modules,
    hr_sampler_name, hr_scheduler, hr_prompt, hr_negative_prompt,
    hr_cfg, hr_distilled_cfg,
    override_settings_texts,
    *script_args
):
    """Queue a txt2img generation task."""
    queue_manager = get_queue_manager()

    # Capture all parameters
    params = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "prompt_styles": prompt_styles,
        "n_iter": n_iter,
        "batch_size": batch_size,
        "cfg_scale": cfg_scale,
        "distilled_cfg_scale": distilled_cfg_scale,
        "height": height,
        "width": width,
        "enable_hr": enable_hr,
        "denoising_strength": denoising_strength,
        "hr_scale": hr_scale,
        "hr_upscaler": hr_upscaler,
        "hr_second_pass_steps": hr_second_pass_steps,
        "hr_resize_x": hr_resize_x,
        "hr_resize_y": hr_resize_y,
        "hr_checkpoint_name": hr_checkpoint_name,
        "hr_additional_modules": hr_additional_modules if hr_additional_modules else [],
        "hr_sampler_name": hr_sampler_name,
        "hr_scheduler": hr_scheduler,
        "hr_prompt": hr_prompt,
        "hr_negative_prompt": hr_negative_prompt,
        "hr_cfg": hr_cfg,
        "hr_distilled_cfg": hr_distilled_cfg,
    }

    # Get sampler from shared options
    try:
        params["sampler_name"] = shared.opts.data.get("sampler_name", "Euler")
        params["scheduler"] = shared.opts.data.get("scheduler", "automatic")
        params["steps"] = shared.opts.data.get("steps", 20)
    except Exception:
        pass

    # Capture current checkpoint
    checkpoint = get_current_checkpoint()

    # Convert script_args to list
    script_args_list = list(script_args) if script_args else []

    # Create task
    task = queue_manager.add_task(
        task_type=TaskType.TXT2IMG,
        params=params,
        checkpoint=checkpoint,
        script_args=script_args_list,
        name=""  # Will auto-generate from prompt
    )

    return f"Task queued: {task.get_display_name()}"


def queue_img2img_task(
    mode, prompt, negative_prompt, prompt_styles,
    init_img, sketch, sketch_fg,
    init_img_with_mask, init_img_with_mask_fg,
    inpaint_color_sketch, inpaint_color_sketch_fg,
    init_img_inpaint, init_mask_inpaint,
    mask_blur, mask_alpha, inpainting_fill,
    n_iter, batch_size, cfg_scale, distilled_cfg_scale, image_cfg_scale,
    denoising_strength, selected_scale_tab, height, width, scale_by,
    resize_mode, inpaint_full_res, inpaint_full_res_padding,
    inpainting_mask_invert,
    img2img_batch_input_dir, img2img_batch_output_dir,
    img2img_batch_inpaint_mask_dir,
    override_settings_texts,
    img2img_batch_use_png_info, img2img_batch_png_info_props,
    img2img_batch_png_info_dir, img2img_batch_source_type,
    img2img_batch_upload,
    *script_args
):
    """Queue an img2img generation task."""
    queue_manager = get_queue_manager()

    # Save init image to temp location for later loading
    init_image_paths = []
    temp_dir = os.path.join(ext_dir, "temp_images")
    os.makedirs(temp_dir, exist_ok=True)

    # Determine which image to use based on mode
    image_to_save = None
    if mode == 0 and init_img is not None:
        image_to_save = init_img
    elif mode == 1 and sketch is not None:
        # Composite sketch
        from PIL import Image
        if sketch_fg is not None:
            image_to_save = Image.alpha_composite(sketch.convert("RGBA"), sketch_fg.convert("RGBA"))
        else:
            image_to_save = sketch
    elif mode == 2 and init_img_with_mask is not None:
        image_to_save = init_img_with_mask
    elif mode == 4 and init_img_inpaint is not None:
        image_to_save = init_img_inpaint

    if image_to_save is not None:
        import uuid
        img_filename = f"{uuid.uuid4()}.png"
        img_path = os.path.join(temp_dir, img_filename)
        image_to_save.save(img_path)
        init_image_paths.append(img_path)

    if not init_image_paths and mode != 5:  # mode 5 is batch
        return "Error: No init image provided for img2img"

    # Capture parameters
    params = {
        "mode": mode,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "prompt_styles": prompt_styles,
        "init_images": init_image_paths,
        "mask_blur": mask_blur,
        "mask_alpha": mask_alpha,
        "inpainting_fill": inpainting_fill,
        "n_iter": n_iter,
        "batch_size": batch_size,
        "cfg_scale": cfg_scale,
        "distilled_cfg_scale": distilled_cfg_scale,
        "image_cfg_scale": image_cfg_scale,
        "denoising_strength": denoising_strength,
        "selected_scale_tab": selected_scale_tab,
        "height": height,
        "width": width,
        "scale_by": scale_by,
        "resize_mode": resize_mode,
        "inpaint_full_res": inpaint_full_res,
        "inpaint_full_res_padding": inpaint_full_res_padding,
        "inpainting_mask_invert": inpainting_mask_invert,
    }

    # Get sampler from shared options
    try:
        params["sampler_name"] = shared.opts.data.get("sampler_name", "Euler")
        params["scheduler"] = shared.opts.data.get("scheduler", "automatic")
        params["steps"] = shared.opts.data.get("steps", 20)
    except Exception:
        pass

    # Capture checkpoint
    checkpoint = get_current_checkpoint()

    # Convert script_args
    script_args_list = list(script_args) if script_args else []

    # Create task
    task = queue_manager.add_task(
        task_type=TaskType.IMG2IMG,
        params=params,
        checkpoint=checkpoint,
        script_args=script_args_list,
        name=""
    )

    return f"Task queued: {task.get_display_name()}"


def render_task_list() -> str:
    """Render the task list as HTML."""
    queue_manager = get_queue_manager()
    executor = get_executor()
    tasks = queue_manager.get_all_tasks()

    if not tasks:
        return "<div class='task-empty'>No tasks in queue. Use the Queue button next to Generate to add tasks.</div>"

    html_parts = ["<div class='task-list'>"]

    for i, task in enumerate(tasks):
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
        actions_html = ""
        if task.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            actions_html += f'<button class="task-btn task-btn-retry" onclick=\'taskSchedulerAction("retry", "{task.id}")\' title="Retry this task">↻</button>'
        if task.status != TaskStatus.RUNNING:
            actions_html += f'<button class="task-btn task-btn-delete" onclick=\'taskSchedulerAction("delete", "{task.id}")\' title="Delete this task">🗑️</button>'

        html_parts.append(f"""
        <div class='task-item {status_class}' data-task-id='{task.id}'>
            <div class='task-index'>{i + 1}</div>
            <div class='task-info'>
                <div class='task-type'>{task.task_type.value}</div>
                <div class='task-prompt' title="{prompt_escaped}">{prompt}</div>
                <div class='task-checkpoint'>Model: {checkpoint_short}</div>
            </div>
            <div class='task-status'><span class='status-badge'>{status_icon} {task.status.value}</span></div>
            <div class='task-actions'>{actions_html}</div>
        </div>
        """)

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
    executor = get_executor()
    queue_manager = get_queue_manager()
    stats = queue_manager.get_stats()

    # Check if there are pending tasks
    if stats['pending'] == 0:
        # No pending tasks - still start but it will be idle
        pass

    executor.start()
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
    """Inject Queue buttons after Generate buttons."""
    elem_id = kwargs.get("elem_id", "")

    if elem_id == "txt2img_generate":
        # Create Queue button for txt2img
        # Note: We'll add the button via JavaScript injection instead
        # because Gradio doesn't allow inserting components after creation
        pass

    elif elem_id == "img2img_generate":
        # Create Queue button for img2img
        pass


def on_app_started(demo, app):
    """Called when the app starts - register API endpoints."""
    from task_scheduler.api import setup_api
    setup_api(app)
    print("[TaskScheduler] Extension loaded successfully")


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
    </style>
    """


# Register callbacks
script_callbacks.on_ui_tabs(on_ui_tabs)
script_callbacks.on_after_component(on_after_component)
script_callbacks.on_app_started(on_app_started)
