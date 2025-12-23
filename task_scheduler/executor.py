"""
Task executor for running queued generation tasks.
Handles background processing with proper thread safety for Forge.
"""
import threading
import time
import traceback
from typing import Optional, Callable, Any
from contextlib import closing, contextmanager

from .models import Task, TaskStatus, TaskType
from .queue_manager import get_queue_manager, QueueManager


@contextmanager
def temporary_settings_override(override_settings: dict):
    """
    Context manager to temporarily apply settings and restore originals after.

    This ensures UI settings (VAE, Clip Skip, etc.) are restored after task
    execution, regardless of success or failure.
    """
    from modules import shared

    if not override_settings:
        yield
        return

    # Save original values
    original_values = {}
    for key in override_settings:
        if hasattr(shared.opts, key):
            original_values[key] = getattr(shared.opts, key)

    print(f"[TaskScheduler] Saved {len(original_values)} original settings")

    try:
        yield
    finally:
        # Restore original values
        restored = []
        for key, value in original_values.items():
            try:
                setattr(shared.opts, key, value)
                restored.append(key)
            except Exception as e:
                print(f"[TaskScheduler] Failed to restore setting '{key}': {e}")

        if restored:
            print(f"[TaskScheduler] Restored {len(restored)} settings: {restored}")


def get_default_script_args(script_runner) -> list[Any]:
    """
    Get default script args for all scripts from the script runner.

    This extracts default values from the UI components that were created
    during Gradio setup. Each alwayson script expects its arguments at
    specific positions in the script_args list.
    """
    if not hasattr(script_runner, 'inputs') or not script_runner.inputs:
        return []

    defaults = []
    for comp in script_runner.inputs:
        # Get the default/current value from the Gradio component
        if hasattr(comp, 'value'):
            defaults.append(comp.value)
        else:
            defaults.append(None)

    return defaults


def merge_script_args_with_defaults(script_args: list, script_runner) -> list[Any]:
    """
    Merge script_args with defaults, replacing None values with defaults.

    This is needed because some scripts (like ControlNet) have complex objects
    that can't be serialized. During queue, those are set to None, and here
    we replace them with proper defaults so the scripts work correctly.
    """
    defaults = get_default_script_args(script_runner)

    if not script_args:
        return defaults

    # Ensure we have enough args
    result = list(script_args)
    while len(result) < len(defaults):
        result.append(None)

    # Replace None values with defaults
    replaced_count = 0
    for i in range(len(result)):
        if result[i] is None and i < len(defaults) and defaults[i] is not None:
            result[i] = defaults[i]
            replaced_count += 1

    if replaced_count > 0:
        print(f"[TaskScheduler] Replaced {replaced_count} None script_args with defaults")

    return result


class TaskExecutor:
    """
    Executes queued tasks in the background.

    Uses Forge's main_thread mechanism for GPU-safe execution.
    """

    _instance: Optional["TaskExecutor"] = None
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

        self._queue: QueueManager = get_queue_manager()
        self._is_running = False
        self._is_paused = False
        self._current_task: Optional[Task] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._status_callbacks: list[Callable] = []
        self._initialized = True

    @property
    def is_running(self) -> bool:
        """Check if the executor is running."""
        return self._is_running

    @property
    def is_paused(self) -> bool:
        """Check if the executor is paused."""
        return self._is_paused

    @property
    def current_task(self) -> Optional[Task]:
        """Get the currently executing task."""
        return self._current_task

    def start(self) -> bool:
        """
        Start processing the queue.

        Returns:
            True if started, False if already running.
        """
        if self._is_running:
            return False

        self._is_running = True
        self._is_paused = False
        self._stop_event.clear()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._notify_status("started")
        print("[TaskScheduler] Queue processing started")
        return True

    def stop(self) -> None:
        """Stop processing after current task completes."""
        if not self._is_running:
            return

        self._is_running = False
        self._stop_event.set()

        self._notify_status("stopped")
        print("[TaskScheduler] Queue processing stopped")

    def pause(self) -> None:
        """Pause processing (current task will complete)."""
        self._is_paused = True
        self._notify_status("paused")
        print("[TaskScheduler] Queue processing paused")

    def resume(self) -> None:
        """Resume processing."""
        self._is_paused = False
        self._notify_status("resumed")
        print("[TaskScheduler] Queue processing resumed")

    def _run_loop(self) -> None:
        """Main execution loop running in background thread."""
        print("[TaskScheduler] Executor run loop started")
        loop_count = 0
        while self._is_running and not self._stop_event.is_set():
            loop_count += 1

            # Check if paused
            if self._is_paused:
                time.sleep(0.5)
                continue

            # Check if Forge is busy with another generation
            if self._is_forge_busy():
                if loop_count % 10 == 1:  # Log every 10 iterations
                    print("[TaskScheduler] Waiting - Forge is busy")
                time.sleep(1.0)
                continue

            # Get next task
            task = self._queue.get_next_task()
            if task is None:
                # No pending tasks - stop the executor
                # User must click "Start Queue" again to process new tasks
                print("[TaskScheduler] No pending tasks, stopping executor")
                break

            print(f"[TaskScheduler] Found task to execute: {task.id}")
            # Execute the task
            self._execute_task(task)

        print("[TaskScheduler] Executor run loop ended")
        self._is_running = False
        self._current_task = None
        self._notify_status("finished")

    def _is_forge_busy(self) -> bool:
        """Check if Forge is currently running a generation."""
        try:
            from modules import shared

            # Check multiple indicators of active generation
            job_count = shared.state.job_count
            job = shared.state.job

            # Only busy if there's an active job name set
            # job_count alone can be stale
            is_busy = bool(job) and job_count > 0

            if is_busy:
                print(f"[TaskScheduler] Forge busy: job='{job}', job_count={job_count}")

            return is_busy
        except Exception as e:
            print(f"[TaskScheduler] Error checking Forge busy state: {e}")
            return False

    def _execute_task(self, task: Task) -> None:
        """Execute a single task."""
        self._current_task = task
        task_id = task.id

        try:
            # Mark as running
            self._queue.set_task_running(task_id)
            print(f"[TaskScheduler] Starting task: {task.get_display_name()}")

            # Execute based on task type
            if task.task_type == TaskType.TXT2IMG:
                result_images, result_info = self._execute_txt2img(task)
            elif task.task_type == TaskType.IMG2IMG:
                result_images, result_info = self._execute_img2img(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")

            # Mark as completed
            self._queue.set_task_completed(task_id, result_images, result_info)
            print(f"[TaskScheduler] Completed task: {task.get_display_name()}")

        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self._queue.set_task_failed(task_id, error_msg)
            print(f"[TaskScheduler] Task failed: {task.get_display_name()}")
            print(f"[TaskScheduler] Error: {e}")

        finally:
            self._current_task = None

    def _execute_txt2img(self, task: Task) -> tuple[list[str], str]:
        """Execute a txt2img task."""
        from modules import processing, scripts, shared
        from modules.processing import StableDiffusionProcessingTxt2Img, process_images
        from modules_forge import main_thread

        params = task.params

        # Build override_settings with checkpoint and UI settings
        override_settings = params.get("override_settings", {}).copy()
        if task.checkpoint:
            override_settings["sd_model_checkpoint"] = task.checkpoint

        # Apply captured UI settings (VAE, Clip Skip, quicksettings, etc.)
        ui_settings = params.get("ui_settings", {})
        if ui_settings:
            override_settings.update(ui_settings)
            print(f"[TaskScheduler] Applying {len(ui_settings)} UI settings: {list(ui_settings.keys())}")

        # Use context manager to ensure settings are restored after execution
        with temporary_settings_override(override_settings):
            # Create processing object
            p = StableDiffusionProcessingTxt2Img(
                outpath_samples=shared.opts.outdir_samples or shared.opts.outdir_txt2img_samples,
                outpath_grids=shared.opts.outdir_grids or shared.opts.outdir_txt2img_grids,
                prompt=params.get("prompt", ""),
                negative_prompt=params.get("negative_prompt", ""),
                styles=params.get("prompt_styles", []),
                batch_size=params.get("batch_size", 1),
                n_iter=params.get("n_iter", 1),
                cfg_scale=params.get("cfg_scale", 7.0),
                distilled_cfg_scale=params.get("distilled_cfg_scale", 3.5),
                width=params.get("width", 512),
                height=params.get("height", 512),
                enable_hr=params.get("enable_hr", False),
                denoising_strength=params.get("denoising_strength", 0.7),
                hr_scale=params.get("hr_scale", 2.0),
                hr_upscaler=params.get("hr_upscaler", "Latent"),
                hr_second_pass_steps=params.get("hr_second_pass_steps", 0),
                hr_resize_x=params.get("hr_resize_x", 0),
                hr_resize_y=params.get("hr_resize_y", 0),
                hr_checkpoint_name=params.get("hr_checkpoint_name"),
                hr_additional_modules=params.get("hr_additional_modules", []),
                hr_sampler_name=params.get("hr_sampler_name"),
                hr_scheduler=params.get("hr_scheduler"),
                hr_prompt=params.get("hr_prompt", ""),
                hr_negative_prompt=params.get("hr_negative_prompt", ""),
                hr_cfg=params.get("hr_cfg"),
                hr_distilled_cfg=params.get("hr_distilled_cfg"),
                override_settings=override_settings,
            )

            # Set sampler
            if "sampler_name" in params:
                p.sampler_name = params["sampler_name"]
            if "scheduler" in params:
                p.scheduler = params["scheduler"]
            if "steps" in params:
                p.steps = params["steps"]
            if "seed" in params:
                p.seed = params["seed"]
            if "subseed" in params:
                p.subseed = params["subseed"]
            if "subseed_strength" in params:
                p.subseed_strength = params["subseed_strength"]

            # Set scripts
            p.scripts = scripts.scripts_txt2img

            # Get script_args from task (will be merged with defaults on main thread)
            # Note: script_args is always raw format (immutable), labeled version is in params
            task_script_args = task.script_args if task.script_args else []

            # Execute via main thread for GPU safety
            # NOTE: merge_script_args_with_defaults must run on main thread because
            # it accesses Gradio component values which are not thread-safe
            def run_generation():
                with closing(p):
                    # Merge task's args with defaults ON MAIN THREAD
                    # This replaces None values (from skipped scripts like ControlNet) with defaults
                    script_args = merge_script_args_with_defaults(task_script_args, scripts.scripts_txt2img)
                    p.script_args = script_args
                    processed = process_images(p)
                    return processed

            processed = main_thread.run_and_wait_result(run_generation)

            # Clear progress
            shared.total_tqdm.clear()

            # Collect results
            result_images = []
            for img in processed.images:
                if hasattr(img, 'already_saved_as') and img.already_saved_as:
                    result_images.append(img.already_saved_as)

            return result_images, processed.info if processed.info else ""

    def _execute_img2img(self, task: Task) -> tuple[list[str], str]:
        """Execute an img2img task."""
        from modules import processing, scripts, shared, images as img_utils
        from modules.processing import StableDiffusionProcessingImg2Img, process_images
        from modules_forge import main_thread
        from PIL import Image

        params = task.params

        # Build override_settings with checkpoint and UI settings
        override_settings = params.get("override_settings", {}).copy()
        if task.checkpoint:
            override_settings["sd_model_checkpoint"] = task.checkpoint

        # Apply captured UI settings (VAE, Clip Skip, quicksettings, etc.)
        ui_settings = params.get("ui_settings", {})
        if ui_settings:
            override_settings.update(ui_settings)
            print(f"[TaskScheduler] Applying {len(ui_settings)} UI settings: {list(ui_settings.keys())}")

        # Load init image(s)
        init_images = []
        init_image_paths = params.get("init_images", [])
        for img_path in init_image_paths:
            try:
                img = Image.open(img_path)
                init_images.append(img)
            except Exception as e:
                print(f"[TaskScheduler] Failed to load init image: {img_path} - {e}")

        if not init_images:
            raise ValueError("No valid init images found for img2img task")

        # Load mask if present
        mask = None
        mask_path = params.get("mask_path")
        if mask_path:
            try:
                mask = Image.open(mask_path)
            except Exception as e:
                print(f"[TaskScheduler] Failed to load mask: {mask_path} - {e}")

        # Use context manager to ensure settings are restored after execution
        with temporary_settings_override(override_settings):
            # Create processing object
            p = StableDiffusionProcessingImg2Img(
                outpath_samples=shared.opts.outdir_samples or shared.opts.outdir_img2img_samples,
                outpath_grids=shared.opts.outdir_grids or shared.opts.outdir_img2img_grids,
                prompt=params.get("prompt", ""),
                negative_prompt=params.get("negative_prompt", ""),
                styles=params.get("prompt_styles", []),
                batch_size=params.get("batch_size", 1),
                n_iter=params.get("n_iter", 1),
                cfg_scale=params.get("cfg_scale", 7.0),
                distilled_cfg_scale=params.get("distilled_cfg_scale", 3.5),
                width=params.get("width", 512),
                height=params.get("height", 512),
                init_images=init_images,
                mask=mask,
                mask_blur=params.get("mask_blur", 4),
                inpainting_fill=params.get("inpainting_fill", 0),
                resize_mode=params.get("resize_mode", 0),
                denoising_strength=params.get("denoising_strength", 0.75),
                image_cfg_scale=params.get("image_cfg_scale", 1.5),
                inpaint_full_res=params.get("inpaint_full_res", False),
                inpaint_full_res_padding=params.get("inpaint_full_res_padding", 32),
                inpainting_mask_invert=params.get("inpainting_mask_invert", 0),
                override_settings=override_settings,
            )

            # Set sampler
            if "sampler_name" in params:
                p.sampler_name = params["sampler_name"]
            if "scheduler" in params:
                p.scheduler = params["scheduler"]
            if "steps" in params:
                p.steps = params["steps"]
            if "seed" in params:
                p.seed = params["seed"]
            if "subseed" in params:
                p.subseed = params["subseed"]
            if "subseed_strength" in params:
                p.subseed_strength = params["subseed_strength"]

            # Set scripts
            p.scripts = scripts.scripts_img2img

            # Get script_args from task (will be merged with defaults on main thread)
            # Note: script_args is always raw format (immutable), labeled version is in params
            task_script_args = task.script_args if task.script_args else []

            # Execute via main thread for GPU safety
            # NOTE: merge_script_args_with_defaults must run on main thread because
            # it accesses Gradio component values which are not thread-safe
            def run_generation():
                with closing(p):
                    # Merge task's args with defaults ON MAIN THREAD
                    # This replaces None values (from skipped scripts like ControlNet) with defaults
                    script_args = merge_script_args_with_defaults(task_script_args, scripts.scripts_img2img)
                    p.script_args = script_args
                    processed = process_images(p)
                    return processed

            processed = main_thread.run_and_wait_result(run_generation)

            # Clear progress
            shared.total_tqdm.clear()

            # Collect results
            result_images = []
            for img in processed.images:
                if hasattr(img, 'already_saved_as') and img.already_saved_as:
                    result_images.append(img.already_saved_as)

            return result_images, processed.info if processed.info else ""

    def register_status_callback(self, callback: Callable) -> None:
        """Register a callback for executor status changes."""
        if callback not in self._status_callbacks:
            self._status_callbacks.append(callback)

    def unregister_status_callback(self, callback: Callable) -> None:
        """Unregister a status callback."""
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)

    def _notify_status(self, status: str) -> None:
        """Notify callbacks of status change."""
        for callback in self._status_callbacks:
            try:
                callback(status)
            except Exception as e:
                print(f"[TaskScheduler] Status callback error: {e}")

    def get_status(self) -> dict:
        """Get current executor status."""
        return {
            "is_running": self._is_running,
            "is_paused": self._is_paused,
            "current_task": self._current_task.to_dict() if self._current_task else None,
            "queue_stats": self._queue.get_stats()
        }


# Convenience function
def get_executor() -> TaskExecutor:
    """Get the global executor instance."""
    return TaskExecutor()
