"""
Queue Interceptor Script - Intercepts generation to capture ALL parameters.

This script acts as an AlwaysOn script that can intercept the generation process
when the user clicks Queue. By piggybacking on the Generate flow, we capture
ALL parameters including extension settings (ADetailer, ControlNet, etc.).
"""
import gradio as gr
from modules import scripts, shared
from modules.processing import StableDiffusionProcessing
import os
import sys
import threading

# Add parent directory to path for imports
ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ext_dir not in sys.path:
    sys.path.insert(0, ext_dir)

from task_scheduler.models import TaskType
from task_scheduler.queue_manager import get_queue_manager

print("[TaskScheduler] Queue interceptor script loaded")


# Global state for queue interception - stored in shared to ensure single instance
# This is necessary because the script can be loaded multiple times
def get_queue_state():
    """Get or create the shared queue intercept state."""
    if not hasattr(shared, '_task_scheduler_intercept_state'):
        shared._task_scheduler_intercept_state = {
            'intercept_next': False,
            'intercept_tab': None,
            'last_result': None,
            'lock': threading.Lock()
        }
    return shared._task_scheduler_intercept_state


class QueueInterceptState:
    """Thread-safe wrapper around the shared state."""

    @property
    def intercept_next(self):
        state = get_queue_state()
        with state['lock']:
            return state['intercept_next']

    @intercept_next.setter
    def intercept_next(self, value):
        state = get_queue_state()
        with state['lock']:
            state['intercept_next'] = value

    @property
    def intercept_tab(self):
        state = get_queue_state()
        with state['lock']:
            return state['intercept_tab']

    @intercept_tab.setter
    def intercept_tab(self, value):
        state = get_queue_state()
        with state['lock']:
            state['intercept_tab'] = value

    @property
    def last_result(self):
        state = get_queue_state()
        with state['lock']:
            return state['last_result']

    @last_result.setter
    def last_result(self, value):
        state = get_queue_state()
        with state['lock']:
            state['last_result'] = value


queue_state = QueueInterceptState()


def set_intercept_mode(tab_name: str) -> bool:
    """Enable interception for the next generation."""
    queue_state.intercept_next = True
    queue_state.intercept_tab = tab_name
    queue_state.last_result = None
    print(f"[TaskScheduler] Intercept mode ENABLED for {tab_name}")
    return True


def get_intercept_result() -> str:
    """Get the result of the last interception."""
    result = queue_state.last_result
    queue_state.last_result = None
    return result


def clear_intercept_mode():
    """Clear the intercept mode."""
    queue_state.intercept_next = False
    queue_state.intercept_tab = None
    print("[TaskScheduler] Intercept mode cleared")


class QueueInterceptorScript(scripts.Script):
    """
    AlwaysOn script that intercepts generation when queue mode is enabled.

    When the user clicks Queue, the JS sets intercept mode and triggers Generate.
    This script's before_process hook captures all parameters and queues the task,
    then aborts the actual generation.
    """

    sorting_priority = -100  # Run very early

    def title(self):
        return "Task Scheduler Queue Interceptor"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        # No UI needed - this is a background interceptor
        return []

    def before_process(self, p: StableDiffusionProcessing, *args):
        """
        Called very early during processing.
        If intercept mode is enabled, capture all params and abort generation.
        """
        print(f"[TaskScheduler] before_process called, intercept_next={queue_state.intercept_next}")

        if not queue_state.intercept_next:
            return

        print("[TaskScheduler] Intercepting generation to queue task...")

        try:
            # Capture all parameters from the processing object
            self._queue_from_processing(p)

            # Clear intercept mode
            clear_intercept_mode()

            # Abort the generation by setting interrupted flag
            shared.state.interrupted = True
            shared.state.textinfo = "Task queued successfully"
            print("[TaskScheduler] Generation aborted, task queued")

        except Exception as e:
            queue_state.last_result = f"Error queuing task: {str(e)}"
            clear_intercept_mode()
            shared.state.interrupted = True
            print(f"[TaskScheduler] Error in queue interceptor: {e}")
            import traceback
            traceback.print_exc()

    def _queue_from_processing(self, p: StableDiffusionProcessing):
        """Extract all parameters from processing object and queue task."""
        from task_scheduler.queue_manager import get_queue_manager
        from task_scheduler.models import Task, TaskType

        queue_manager = get_queue_manager()

        # Determine task type
        is_img2img = hasattr(p, 'init_images') and p.init_images
        task_type = TaskType.IMG2IMG if is_img2img else TaskType.TXT2IMG

        # Build comprehensive params dict from processing object
        params = {
            "prompt": p.prompt,
            "negative_prompt": p.negative_prompt,
            "styles": getattr(p, 'styles', []),
            "seed": p.seed,
            "subseed": p.subseed,
            "subseed_strength": p.subseed_strength,
            "seed_resize_from_h": p.seed_resize_from_h,
            "seed_resize_from_w": p.seed_resize_from_w,
            "sampler_name": p.sampler_name,
            "scheduler": getattr(p, 'scheduler', None),
            "batch_size": p.batch_size,
            "n_iter": p.n_iter,
            "steps": p.steps,
            "cfg_scale": p.cfg_scale,
            "distilled_cfg_scale": getattr(p, 'distilled_cfg_scale', None),
            "width": p.width,
            "height": p.height,
            "restore_faces": p.restore_faces,
            "tiling": p.tiling,
            "do_not_save_samples": p.do_not_save_samples,
            "do_not_save_grid": p.do_not_save_grid,
        }

        # Capture UI-visible settings from shared.opts
        # 1. Get user's configured quicksettings (shown in top bar)
        # 2. Add essential settings that should always be captured
        try:
            # Start with essential settings that affect generation
            essential_settings = {
                "sd_vae",                        # VAE
                "CLIP_stop_at_last_layers",      # Clip Skip
                "eta_noise_seed_delta",          # ENSD
                "randn_source",                  # RNG source
            }

            # Get user's configured quicksettings
            user_quicksettings = set()
            if hasattr(shared.opts, 'quick_setting_list') and shared.opts.quick_setting_list:
                user_quicksettings = set(shared.opts.quick_setting_list)

            # Combine both sets
            settings_to_capture = essential_settings | user_quicksettings

            # Capture all values
            captured_settings = {}
            for setting_name in settings_to_capture:
                if hasattr(shared.opts, setting_name):
                    value = getattr(shared.opts, setting_name)
                    captured_settings[setting_name] = value

            params["ui_settings"] = captured_settings
            print(f"[TaskScheduler] Captured {len(captured_settings)} UI settings: {list(captured_settings.keys())}")
        except Exception as e:
            print(f"[TaskScheduler] Could not capture UI settings: {e}")

        # Txt2img specific parameters
        if task_type == TaskType.TXT2IMG:
            params.update({
                "enable_hr": getattr(p, 'enable_hr', False),
                "denoising_strength": getattr(p, 'denoising_strength', 0.7),
                "hr_scale": getattr(p, 'hr_scale', 2.0),
                "hr_upscaler": getattr(p, 'hr_upscaler', None),
                "hr_second_pass_steps": getattr(p, 'hr_second_pass_steps', 0),
                "hr_resize_x": getattr(p, 'hr_resize_x', 0),
                "hr_resize_y": getattr(p, 'hr_resize_y', 0),
                "hr_checkpoint_name": getattr(p, 'hr_checkpoint_name', None),
                "hr_sampler_name": getattr(p, 'hr_sampler_name', None),
                "hr_scheduler": getattr(p, 'hr_scheduler', None),
                "hr_prompt": getattr(p, 'hr_prompt', ''),
                "hr_negative_prompt": getattr(p, 'hr_negative_prompt', ''),
                "hr_cfg": getattr(p, 'hr_cfg', None),
                "hr_distilled_cfg": getattr(p, 'hr_distilled_cfg', None),
            })

        # Img2img specific parameters
        if task_type == TaskType.IMG2IMG:
            params.update({
                "denoising_strength": getattr(p, 'denoising_strength', 0.75),
                "resize_mode": getattr(p, 'resize_mode', 0),
                "image_cfg_scale": getattr(p, 'image_cfg_scale', None),
                "mask_blur": getattr(p, 'mask_blur', 4),
                "inpainting_fill": getattr(p, 'inpainting_fill', 0),
                "inpaint_full_res": getattr(p, 'inpaint_full_res', False),
                "inpaint_full_res_padding": getattr(p, 'inpaint_full_res_padding', 32),
                "inpainting_mask_invert": getattr(p, 'inpainting_mask_invert', 0),
            })

            # Save init images to temp files
            if hasattr(p, 'init_images') and p.init_images:
                import uuid
                temp_dir = os.path.join(ext_dir, "temp_images")
                os.makedirs(temp_dir, exist_ok=True)

                init_image_paths = []
                for i, img in enumerate(p.init_images):
                    if img is not None:
                        img_filename = f"{uuid.uuid4()}.png"
                        img_path = os.path.join(temp_dir, img_filename)
                        img.save(img_path)
                        init_image_paths.append(img_path)

                params["init_images"] = init_image_paths

            # Save mask if present
            if hasattr(p, 'image_mask') and p.image_mask is not None:
                import uuid
                temp_dir = os.path.join(ext_dir, "temp_images")
                os.makedirs(temp_dir, exist_ok=True)
                mask_filename = f"mask_{uuid.uuid4()}.png"
                mask_path = os.path.join(temp_dir, mask_filename)
                p.image_mask.save(mask_path)
                params["mask_path"] = mask_path

        # Capture override settings
        if hasattr(p, 'override_settings') and p.override_settings:
            params["override_settings"] = dict(p.override_settings)

        # Capture extra generation params (includes extension params!)
        if hasattr(p, 'extra_generation_params') and p.extra_generation_params:
            params["extra_generation_params"] = dict(p.extra_generation_params)
            print(f"[TaskScheduler] Captured extra_generation_params: {list(p.extra_generation_params.keys())}")

        # Get current checkpoint
        checkpoint = shared.opts.sd_model_checkpoint or ""

        # Capture script_args - this includes ALL extension settings!
        # p.script_args contains the full list of all script arguments
        # We need to serialize them properly (some might be Gradio components or complex objects)
        # IMPORTANT: Keep raw script_args immutable for execution, store labeled version separately
        script_args = []  # Raw values for execution (immutable)
        script_args_labeled = None  # Labeled version for display only

        # Try to get script args mapping for labels (optional plugin)
        args_mapping = None
        try:
            from task_scheduler.script_args_mapper import get_cached_mapping
            args_mapping = get_cached_mapping()
            print(f"[TaskScheduler] Script args mapper returned: {len(args_mapping) if args_mapping else 0} mappings")
            if args_mapping:
                script_args_labeled = []
            else:
                print("[TaskScheduler] Mapper returned empty, labels will not be available")
        except ImportError as e:
            print(f"[TaskScheduler] Mapper import failed: {e}")
        except Exception as e:
            print(f"[TaskScheduler] Error loading script args mapper: {e}")
            import traceback
            traceback.print_exc()

        if hasattr(p, 'script_args') and p.script_args:
            for i, arg in enumerate(p.script_args):
                # Serialize the value
                serialized_value = None
                try:
                    import json
                    json.dumps(arg)
                    serialized_value = arg
                except (TypeError, ValueError):
                    if hasattr(arg, 'value'):
                        serialized_value = arg.value
                    elif arg is None:
                        serialized_value = None
                    else:
                        serialized_value = str(arg)

                # Always store raw value
                script_args.append(serialized_value)

                # Build labeled entry if mapping available (for display only)
                if script_args_labeled is not None:
                    if args_mapping and i in args_mapping:
                        info = args_mapping[i]
                        script_args_labeled.append({
                            "index": i,
                            "name": info.get("name", f"arg_{i}"),
                            "label": info.get("label", f"Argument {i}"),
                            "script": info.get("script"),
                            "type": info.get("type", "unknown"),
                            "value": serialized_value
                        })
                    else:
                        script_args_labeled.append({
                            "index": i,
                            "name": f"arg_{i}",
                            "label": f"Argument {i}",
                            "script": None,
                            "type": "unknown",
                            "value": serialized_value
                        })

        print(f"[TaskScheduler] Captured {len(script_args)} script_args (raw format)")

        # Store labeled version in params for display (if available)
        if script_args_labeled:
            params["_script_args_labeled"] = script_args_labeled
            print(f"[TaskScheduler] Stored labeled script_args for display")

        # Create the task - script_args stays raw for execution
        task = queue_manager.add_task(
            task_type=task_type,
            params=params,
            checkpoint=checkpoint,
            script_args=script_args,  # Raw values only!
            name=""  # Will auto-generate from prompt
        )

        queue_state.last_result = f"Task queued: {task.get_display_name()}"
        print(f"[TaskScheduler] {queue_state.last_result}")
