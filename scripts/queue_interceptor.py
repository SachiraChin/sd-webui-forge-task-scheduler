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
            'last_task_data': None,  # Full task data for bookmarks
            'intercept_timestamp': None,  # When intercept was set
            'lock': threading.Lock()
        }
    return shared._task_scheduler_intercept_state


def get_intercept_timeout() -> float:
    """Get the intercept timeout from settings."""
    return getattr(shared.opts, 'task_scheduler_intercept_timeout', 10.0)


class QueueInterceptState:
    """Thread-safe wrapper around the shared state."""

    @property
    def intercept_next(self):
        state = get_queue_state()
        with state['lock']:
            # Check for timeout - auto-clear if intercept has been set too long
            if state['intercept_next'] and state['intercept_timestamp'] is not None:
                import time
                elapsed = time.time() - state['intercept_timestamp']
                timeout = get_intercept_timeout()
                if elapsed > timeout:
                    print(f"[TaskScheduler] Intercept mode timed out after {elapsed:.1f}s (timeout: {timeout}s), auto-clearing")
                    state['intercept_next'] = False
                    state['intercept_tab'] = None
                    state['intercept_timestamp'] = None
                    return False
            return state['intercept_next']

    @intercept_next.setter
    def intercept_next(self, value):
        state = get_queue_state()
        with state['lock']:
            state['intercept_next'] = value
            if value:
                import time
                state['intercept_timestamp'] = time.time()
            else:
                state['intercept_timestamp'] = None

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

    @property
    def last_task_data(self):
        state = get_queue_state()
        with state['lock']:
            return state.get('last_task_data')

    @last_task_data.setter
    def last_task_data(self, value):
        state = get_queue_state()
        with state['lock']:
            state['last_task_data'] = value


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


def get_last_task_data() -> dict:
    """Get the full task data from the last interception (for bookmarks)."""
    data = queue_state.last_task_data
    queue_state.last_task_data = None
    return data


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
        from task_scheduler.param_capture import get_capture_strategy

        queue_manager = get_queue_manager()

        # Determine task type
        is_img2img = hasattr(p, 'init_images') and p.init_images
        task_type = TaskType.IMG2IMG if is_img2img else TaskType.TXT2IMG

        # Check if dynamic capture is enabled in settings
        use_dynamic = getattr(shared.opts, 'task_scheduler_dynamic_capture', False)

        # Get the appropriate capture strategy
        capture_strategy = get_capture_strategy(use_dynamic=use_dynamic)
        capture_format = capture_strategy.CAPTURE_FORMAT

        print(f"[TaskScheduler] Using {'dynamic' if use_dynamic else 'legacy'} capture strategy")

        # Capture all parameters
        params, script_args, checkpoint = capture_strategy.capture(p)

        # Create the task
        task = queue_manager.add_task(
            task_type=task_type,
            params=params,
            checkpoint=checkpoint,
            script_args=script_args,
            name="",  # Will auto-generate from prompt
            capture_format=capture_format
        )

        queue_state.last_result = f"Task queued: {task.get_display_name()}"
        # Store task data for bookmark creation
        queue_state.last_task_data = {
            'status': 'queued',
            'task_id': task.id,
            'task_type': task_type.value,
            'params': params,
            'checkpoint': checkpoint,
            'script_args': script_args
        }
        print(f"[TaskScheduler] {queue_state.last_result}")
