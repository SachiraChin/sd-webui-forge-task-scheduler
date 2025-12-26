"""
Task executor for running queued generation tasks.
Handles background processing with proper thread safety for Forge.
"""
import os
import threading
import time
import traceback
from datetime import datetime
from typing import Optional, Callable, Any
from contextlib import closing, contextmanager

from .models import Task, TaskStatus, TaskType
from .queue_manager import get_queue_manager, QueueManager


def get_output_subfolder() -> str:
    """
    Get the output subfolder from settings, formatted with current datetime.

    Returns empty string if no subfolder is configured.
    The subfolder template supports strftime format codes (e.g., %Y-%m-%d).
    """
    from modules import shared

    subfolder_template = getattr(shared.opts, 'task_scheduler_output_subfolder', '')

    if not subfolder_template:
        return ''

    try:
        # Format the template with current datetime
        subfolder = datetime.now().strftime(subfolder_template)
        return subfolder
    except Exception as e:
        print(f"[TaskScheduler] Error formatting subfolder template '{subfolder_template}': {e}")
        return ''


@contextmanager
def output_subfolder_override():
    """
    Context manager to temporarily append our subfolder to SD WebUI's directory pattern.

    This modifies 'directories_filename_pattern' to append our subfolder at the END,
    so images are saved to: base_path/SD_WebUI_subdirs/our_subfolder/
    All metadata and references remain correct since SD WebUI handles the save.
    """
    from modules import shared

    subfolder = get_output_subfolder()
    if not subfolder:
        yield
        return

    # Get the current directory pattern
    original_pattern = getattr(shared.opts, 'directories_filename_pattern', '')

    # Append our subfolder to the pattern
    # Use forward slash as it works on all platforms for this setting
    if original_pattern:
        new_pattern = f"{original_pattern}/{subfolder}"
    else:
        new_pattern = subfolder

    print(f"[TaskScheduler] Output subfolder: {subfolder}")
    print(f"[TaskScheduler] Directory pattern: '{original_pattern}' -> '{new_pattern}'")

    try:
        shared.opts.directories_filename_pattern = new_pattern
        yield
    finally:
        # Restore original pattern
        shared.opts.directories_filename_pattern = original_pattern
        print(f"[TaskScheduler] Restored directory pattern: '{original_pattern}'")


def switch_model_if_needed(checkpoint_name: str) -> bool:
    """
    Switch to the specified checkpoint model if not already loaded.

    Must be called from the main thread.

    Args:
        checkpoint_name: The checkpoint name to switch to

    Returns:
        True if model was switched, False if already loaded or switch failed
    """
    from modules import shared, sd_models

    if not checkpoint_name:
        return False

    # Get current loaded model name
    current_model = None
    if shared.sd_model and hasattr(shared.sd_model, 'sd_checkpoint_info') and shared.sd_model.sd_checkpoint_info:
        current_model = shared.sd_model.sd_checkpoint_info.name_for_extra
        if not current_model:
            current_model = shared.sd_model.sd_checkpoint_info.name

    print(f"[TaskScheduler] Current model: {current_model}")
    print(f"[TaskScheduler] Target model: {checkpoint_name}")

    # Check if we need to switch
    if current_model and checkpoint_name in current_model:
        print(f"[TaskScheduler] Model already loaded, no switch needed")
        return False

    # Also check the other way (in case checkpoint_name is a substring or vice versa)
    if current_model and current_model in checkpoint_name:
        print(f"[TaskScheduler] Model already loaded (reverse match), no switch needed")
        return False

    # Find the checkpoint info
    checkpoint_info = sd_models.get_closet_checkpoint_match(checkpoint_name)
    if not checkpoint_info:
        print(f"[TaskScheduler] WARNING: Checkpoint not found: {checkpoint_name}")
        return False

    print(f"[TaskScheduler] Switching model to: {checkpoint_info.name}")

    try:
        # Reload model weights
        sd_models.reload_model_weights(info=checkpoint_info)
        print(f"[TaskScheduler] Model switched successfully")
        return True
    except Exception as e:
        print(f"[TaskScheduler] Failed to switch model: {e}")
        import traceback
        traceback.print_exc()
        return False


@contextmanager
def temporary_settings_override(override_settings: dict):
    """
    Context manager to temporarily apply settings and restore originals after.

    This ensures UI settings (VAE, Clip Skip, etc.) are restored after task
    execution, regardless of success or failure.

    Note: sd_model_checkpoint is EXCLUDED here - model switching is handled
    separately via switch_model_if_needed() to ensure it actually loads.
    """
    from modules import shared

    if not override_settings:
        yield
        return

    # Exclude sd_model_checkpoint - model switching handled separately
    settings_to_apply = {k: v for k, v in override_settings.items() if k != "sd_model_checkpoint"}

    # Save original values
    original_values = {}
    for key in settings_to_apply:
        if hasattr(shared.opts, key):
            original_values[key] = getattr(shared.opts, key)

    # Always save forge_additional_modules so we can restore VAE after task
    # (even if task doesn't specify it, we might clear the UI's VAE)
    if "forge_additional_modules" not in original_values:
        original_values["forge_additional_modules"] = getattr(shared.opts, "forge_additional_modules", [])

    print(f"[TaskScheduler] Saved {len(original_values)} original settings")

    # Apply new settings before task execution
    applied = []
    for key, value in settings_to_apply.items():
        try:
            if hasattr(shared.opts, key):
                setattr(shared.opts, key, value)
                applied.append(key)
        except Exception as e:
            print(f"[TaskScheduler] Failed to apply setting '{key}': {e}")

    if applied:
        print(f"[TaskScheduler] Applied {len(applied)} settings: {applied}")

    # Handle VAE switch if needed
    # For Forge, VAE is in forge_additional_modules; for standard A1111, it's in sd_vae
    forge_modules = settings_to_apply.get("forge_additional_modules")
    sd_vae_setting = settings_to_apply.get("sd_vae")

    # Forge-style VAE handling
    # If forge_additional_modules is in settings, use it (could be empty list to clear VAE)
    # If forge_additional_modules is NOT in settings, task was created without VAE - clear it
    try:
        current_modules = getattr(shared.opts, "forge_additional_modules", [])

        if "forge_additional_modules" in settings_to_apply:
            # Task has explicit VAE setting (could be empty list or list with VAE path)
            target_modules = forge_modules if forge_modules else []
        else:
            # Task doesn't have forge_additional_modules - means no VAE was selected
            target_modules = []
            if current_modules:
                print(f"[TaskScheduler] Task has no VAE, clearing UI's VAE")

        if list(target_modules) != list(current_modules):
            setattr(shared.opts, "forge_additional_modules", target_modules)
            print(f"[TaskScheduler] Set forge_additional_modules: {target_modules}")

            # Call Forge's refresh function to update model_data.forge_loading_parameters
            # This is required for Forge to actually use the new VAE setting
            try:
                from modules_forge.main_entry import refresh_model_loading_parameters
                refresh_model_loading_parameters()
                print(f"[TaskScheduler] Refreshed Forge loading parameters")
            except ImportError:
                print(f"[TaskScheduler] Could not import refresh_model_loading_parameters")

            # Force model reload to apply new VAE (or clear VAE if empty)
            from modules import sd_models
            if shared.sd_model and hasattr(shared.sd_model, 'sd_checkpoint_info'):
                print(f"[TaskScheduler] Reloading model to apply VAE change...")
                sd_models.reload_model_weights(info=shared.sd_model.sd_checkpoint_info)
        else:
            print(f"[TaskScheduler] forge_additional_modules unchanged, skipping reload")
    except Exception as e:
        print(f"[TaskScheduler] Failed to handle forge_additional_modules: {e}")

    if sd_vae_setting and sd_vae_setting not in ("Automatic", "None", ""):
        # Standard A1111-style VAE reload
        try:
            from modules import sd_vae
            sd_vae.reload_vae_weights()
            print(f"[TaskScheduler] Reloaded VAE: {sd_vae_setting}")
        except Exception as e:
            print(f"[TaskScheduler] Failed to reload VAE: {e}")

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

        # Restore VAE if it was changed
        # For Forge, restore forge_additional_modules; for A1111, reload sd_vae
        if "forge_additional_modules" in original_values:
            try:
                current_modules = getattr(shared.opts, "forge_additional_modules", [])
                original_modules = original_values["forge_additional_modules"]
                if list(original_modules) != list(current_modules):
                    setattr(shared.opts, "forge_additional_modules", original_modules)
                    print(f"[TaskScheduler] Restored forge_additional_modules: {original_modules}")

                    # Call Forge's refresh function to update model_data.forge_loading_parameters
                    try:
                        from modules_forge.main_entry import refresh_model_loading_parameters
                        refresh_model_loading_parameters()
                    except ImportError:
                        pass

                    # Force model reload to restore original VAE
                    from modules import sd_models
                    if shared.sd_model and hasattr(shared.sd_model, 'sd_checkpoint_info'):
                        print(f"[TaskScheduler] Reloading model to restore VAE...")
                        sd_models.reload_model_weights(info=shared.sd_model.sd_checkpoint_info)
            except Exception as e:
                print(f"[TaskScheduler] Failed to restore forge_additional_modules: {e}")
        elif "sd_vae" in original_values:
            try:
                from modules import sd_vae
                sd_vae.reload_vae_weights()
                print(f"[TaskScheduler] Restored VAE: {original_values['sd_vae']}")
            except Exception as e:
                print(f"[TaskScheduler] Failed to restore VAE: {e}")


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
    Also deserializes ControlNet units if they were serialized.

    This is needed because some scripts (like ControlNet) have complex objects
    that can't be serialized. During queue, those are set to None, and here
    we replace them with proper defaults so the scripts work correctly.
    """
    defaults = get_default_script_args(script_runner)

    if not script_args:
        return defaults

    # Try to import ControlNet helper for deserialization
    deserialize_arg = None
    try:
        from task_scheduler.controlnet_helper import deserialize_script_arg
        deserialize_arg = deserialize_script_arg
    except ImportError:
        pass

    # Ensure we have enough args
    result = list(script_args)
    while len(result) < len(defaults):
        result.append(None)

    # Process args: deserialize ControlNet units and replace None with defaults
    replaced_count = 0
    deserialized_count = 0
    for i in range(len(result)):
        # Try to deserialize ControlNet units first
        if deserialize_arg is not None and isinstance(result[i], dict):
            if result[i].get('_is_controlnet_unit'):
                deserialized = deserialize_arg(result[i])
                if deserialized is not None:
                    result[i] = deserialized
                    deserialized_count += 1
                    continue

        # Replace None values with defaults
        if result[i] is None and i < len(defaults) and defaults[i] is not None:
            result[i] = defaults[i]
            replaced_count += 1

    if replaced_count > 0:
        print(f"[TaskScheduler] Replaced {replaced_count} None script_args with defaults")
    if deserialized_count > 0:
        print(f"[TaskScheduler] Deserialized {deserialized_count} ControlNet units")

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
        self._is_stopping = False  # True when stop requested, waiting for task to finish
        self._status_text = ""  # Current status text for UI display
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
    def is_stopping(self) -> bool:
        """Check if the executor is in the process of stopping."""
        return self._is_stopping

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
        self._is_stopping = False
        self._status_text = ""
        self._stop_event.clear()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._notify_status("started")
        print("[TaskScheduler] Queue processing started")
        return True

    def stop(self) -> None:
        """
        Stop processing immediately by interrupting current task.

        This calls Forge's interrupt() to stop the current generation,
        then marks the task as 'stopped'.
        """
        if not self._is_running:
            return

        self._is_stopping = True
        self._is_running = False
        self._stop_event.set()

        # Notify UI that we're stopping
        self._notify_status("stopping")
        print("[TaskScheduler] Stopping queue processing...")

        # Interrupt the current generation
        try:
            from modules import shared
            shared.state.interrupt()
            print("[TaskScheduler] Sent interrupt signal to Forge")
        except Exception as e:
            print(f"[TaskScheduler] Failed to send interrupt: {e}")

    def pause(self) -> None:
        """
        Pause processing.

        Behavior depends on the 'pause_with_state_saving' setting:
        - Simple mode (default): Wait for current task to complete, then pause
        - Advanced mode: Wait for current image to complete, save state for resume
        """
        from modules import shared

        self._is_paused = True

        # Check if advanced pause mode is enabled
        pause_with_state = getattr(shared.opts, 'task_scheduler_pause_with_state_saving', False)

        if pause_with_state and self._current_task is not None:
            # Advanced mode: signal Forge to stop after current image
            try:
                shared.state.stop_generating()
                self._notify_status("pausing_image")
                print("[TaskScheduler] Pausing after current image (state saving enabled)")
            except Exception as e:
                print(f"[TaskScheduler] Failed to call stop_generating: {e}")
                self._notify_status("pausing_task")
        else:
            # Simple mode: just wait for current task to complete
            self._notify_status("pausing_task")
            print("[TaskScheduler] Pausing after current task completes")

    def resume(self) -> None:
        """Resume processing."""
        self._is_paused = False
        self._status_text = ""  # Clear pausing status
        self._notify_status("resumed")
        print("[TaskScheduler] Queue processing resumed")

    def run_single_task(self, task_id: str) -> None:
        """
        Run a single task immediately in a background thread.

        This runs just one specific task, not the full queue.
        """
        if self._current_task is not None:
            raise RuntimeError("Another task is already running")

        task = self._queue.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        # Run in background thread
        def run_task():
            try:
                self._is_running = True
                self._execute_task(task)
            finally:
                self._is_running = False
                self._current_task = None

        thread = threading.Thread(target=run_task, daemon=True)
        thread.start()
        print(f"[TaskScheduler] Running single task: {task.get_display_name()}")

    def _run_loop(self) -> None:
        """Main execution loop running in background thread."""
        from modules import shared

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

            # First check for paused tasks that need resuming (advanced mode)
            paused_task = self._queue.get_paused_task()
            if paused_task is not None:
                print(f"[TaskScheduler] Resuming paused task: {paused_task.id}")
                # Adjust n_iter for remaining iterations
                remaining_iter = paused_task.original_n_iter - paused_task.completed_iterations
                if remaining_iter > 0:
                    paused_task.params["n_iter"] = remaining_iter
                    print(f"[TaskScheduler] Resuming with {remaining_iter} remaining iterations")
                self._execute_task(paused_task)
                continue

            # Get next pending task
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
        self._is_stopping = False  # Reset stopping flag
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
        from modules import shared

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

            # Check if we were stopped or paused during execution
            was_interrupted = shared.state.interrupted
            was_stopped_generating = shared.state.stopping_generation

            if self._is_stopping or was_interrupted:
                # Task was interrupted by Stop button
                self._queue.set_task_stopped(task_id, result_images, result_info)
                self._notify_status("stopped")
                print(f"[TaskScheduler] Task stopped: {task.get_display_name()}")
                self._is_stopping = False  # Reset the flag
            elif self._is_paused and was_stopped_generating:
                # Advanced pause mode: task was paused mid-execution
                pause_with_state = getattr(shared.opts, 'task_scheduler_pause_with_state_saving', False)
                if pause_with_state:
                    # Calculate completed iterations from results
                    # Each iteration produces batch_size images
                    batch_size = task.params.get("batch_size", 1)
                    completed_iter = len(result_images) // batch_size if result_images else 0
                    original_iter = task.original_n_iter if task.original_n_iter > 0 else task.params.get("n_iter", 1)

                    self._queue.set_task_paused(
                        task_id,
                        completed_iterations=completed_iter,
                        original_n_iter=original_iter,
                        result_images=result_images,
                        result_info=result_info
                    )
                    self._notify_status("paused")
                    print(f"[TaskScheduler] Task paused: {task.get_display_name()} ({completed_iter}/{original_iter} iterations)")
                else:
                    # Simple pause mode - task completed normally
                    self._queue.set_task_completed(task_id, result_images, result_info)
                    self._notify_status("paused")
                    print(f"[TaskScheduler] Task completed, queue paused: {task.get_display_name()}")
            else:
                # Normal completion
                self._queue.set_task_completed(task_id, result_images, result_info)
                print(f"[TaskScheduler] Completed task: {task.get_display_name()}")

        except Exception as e:
            # Check if this was an interrupt that manifested as an exception
            if self._is_stopping or shared.state.interrupted:
                # Get any partial results
                self._queue.set_task_stopped(task_id, [], "")
                self._notify_status("stopped")
                print(f"[TaskScheduler] Task stopped (exception): {task.get_display_name()}")
                self._is_stopping = False
            else:
                error_msg = f"{str(e)}\n{traceback.format_exc()}"
                self._queue.set_task_failed(task_id, error_msg)
                print(f"[TaskScheduler] Task failed: {task.get_display_name()}")
                print(f"[TaskScheduler] Error: {e}")

        finally:
            self._current_task = None

    def _execute_txt2img(self, task: Task) -> tuple[list[str], str]:
        """Execute a txt2img task."""
        from modules import scripts, shared
        from modules.processing import process_images
        from modules_forge import main_thread
        from .param_capture import get_restore_strategy

        params = task.params

        # Build override_settings: UI settings first, then model overrides on top
        ui_settings = params.get("ui_settings", {})
        model_overrides = params.get("override_settings", {})

        override_settings = ui_settings.copy() if ui_settings else {}
        if ui_settings:
            print(f"[TaskScheduler] Applying {len(ui_settings)} UI settings: {list(ui_settings.keys())}")

        if model_overrides:
            override_settings.update(model_overrides)
            print(f"[TaskScheduler] Applying {len(model_overrides)} model overrides: {list(model_overrides.keys())}")

        if task.checkpoint:
            override_settings["sd_model_checkpoint"] = task.checkpoint

        # Use context managers to ensure settings are restored after execution
        with temporary_settings_override(override_settings), output_subfolder_override():
            # Get restore strategy and create processing object
            restore_strategy = get_restore_strategy(task.capture_format)
            p = restore_strategy.create_txt2img(params, override_settings)

            # Get script_args from task (will be merged with defaults on main thread)
            task_script_args = task.script_args if task.script_args else []
            target_checkpoint = task.checkpoint

            def run_generation():
                # Switch model if needed (must be on main thread)
                if target_checkpoint:
                    switch_model_if_needed(target_checkpoint)

                with closing(p):
                    # Merge task's args with defaults ON MAIN THREAD
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
        from modules import scripts, shared
        from modules.processing import process_images
        from modules_forge import main_thread
        from .param_capture import get_restore_strategy

        params = task.params

        # Build override_settings: UI settings first, then model overrides on top
        ui_settings = params.get("ui_settings", {})
        model_overrides = params.get("override_settings", {})

        override_settings = ui_settings.copy() if ui_settings else {}
        if ui_settings:
            print(f"[TaskScheduler] Applying {len(ui_settings)} UI settings: {list(ui_settings.keys())}")

        if model_overrides:
            override_settings.update(model_overrides)
            print(f"[TaskScheduler] Applying {len(model_overrides)} model overrides: {list(model_overrides.keys())}")

        if task.checkpoint:
            override_settings["sd_model_checkpoint"] = task.checkpoint

        # Use context managers to ensure settings are restored after execution
        with temporary_settings_override(override_settings), output_subfolder_override():
            # Get restore strategy and create processing object
            restore_strategy = get_restore_strategy(task.capture_format)
            p = restore_strategy.create_img2img(params, override_settings)

            # Get script_args from task (will be merged with defaults on main thread)
            task_script_args = task.script_args if task.script_args else []
            target_checkpoint = task.checkpoint

            def run_generation():
                # Switch model if needed (must be on main thread)
                if target_checkpoint:
                    switch_model_if_needed(target_checkpoint)

                with closing(p):
                    # Merge task's args with defaults ON MAIN THREAD
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
        self._status_text = status  # Store for API access
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
            "is_stopping": self._is_stopping,
            "status_text": self._status_text,
            "current_task": self._current_task.to_dict() if self._current_task else None,
            "queue_stats": self._queue.get_stats()
        }


# Convenience function
def get_executor() -> TaskExecutor:
    """Get the global executor instance."""
    return TaskExecutor()
