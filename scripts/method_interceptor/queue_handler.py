"""
Interceptor Method - Queue Handler

This method uses the interceptor pattern (like Agent Scheduler):
1. Queue button sets intercept mode
2. Triggers Generate button click
3. AlwaysOn script captures ALL params from StableDiffusionProcessing
4. Aborts generation after queuing

Pros:
- Captures ALL parameters including VAE, Clip Skip, extension settings
- Parameters are fully resolved in the processing object
- Proven approach used by Agent Scheduler

Cons:
- Briefly starts generation before aborting
- Shows progress bar momentarily
"""
import gradio as gr
from typing import Optional
import os
import sys

# Add parent directories to path for imports
scripts_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ext_dir = os.path.dirname(scripts_dir)
if ext_dir not in sys.path:
    sys.path.insert(0, ext_dir)
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# Import interceptor module (must be after path setup)
from queue_interceptor import set_intercept_mode

# Global references to UI components
_txt2img_queue_btn: Optional[gr.Button] = None
_img2img_queue_btn: Optional[gr.Button] = None
_txt2img_generate_btn: Optional[gr.Button] = None
_img2img_generate_btn: Optional[gr.Button] = None


def set_intercept_and_notify(tab_name: str):
    """
    Set intercept mode and return JavaScript to trigger Generate.
    This function is called when Queue button is clicked.
    """
    set_intercept_mode(tab_name)
    print(f"[TaskScheduler:Interceptor] Intercept mode set for {tab_name}")

    # Return a signal that JS will use to trigger Generate
    return f"intercept:{tab_name}"


def on_after_component(component, **kwargs):
    """Detect Generate buttons and create Queue buttons next to them."""
    global _txt2img_generate_btn, _img2img_generate_btn
    global _txt2img_queue_btn, _img2img_queue_btn

    elem_id = kwargs.get("elem_id", "")

    if elem_id == "txt2img_generate":
        _txt2img_generate_btn = component
        print(f"[TaskScheduler:Interceptor] Found txt2img_generate button: {component._id}")
        _txt2img_queue_btn = gr.Button(
            "Queue",
            variant="secondary",
            elem_id="txt2img_queue",
            min_width=60
        )
        print(f"[TaskScheduler:Interceptor] Created txt2img Queue button: {_txt2img_queue_btn._id}")

    elif elem_id == "img2img_generate":
        _img2img_generate_btn = component
        print(f"[TaskScheduler:Interceptor] Found img2img_generate button: {component._id}")
        _img2img_queue_btn = gr.Button(
            "Queue",
            variant="secondary",
            elem_id="img2img_queue",
            min_width=60
        )
        print(f"[TaskScheduler:Interceptor] Created img2img Queue button: {_img2img_queue_btn._id}")


def setup_queue_buttons(demo):
    """
    Setup Queue buttons with interceptor behavior.
    The buttons will set intercept mode and trigger Generate via JavaScript.
    Includes proper state management to prevent stuck buttons.
    """
    global _txt2img_queue_btn, _img2img_queue_btn

    print("[TaskScheduler:Interceptor] Setting up Queue buttons...")

    # JavaScript for handling queue button with state management
    queue_button_js = """
    (tabName) => {
        const btnId = tabName + '_queue';
        const generateBtnId = tabName + '_generate';
        const btn = document.getElementById(btnId);
        const generateBtn = document.getElementById(generateBtnId);

        if (!btn) {
            console.error('[TaskScheduler] Queue button not found:', btnId);
            return [];
        }

        // Check if already processing
        if (btn.dataset.queueState === 'processing') {
            console.log('[TaskScheduler] Queue already processing, ignoring click');
            return [];
        }

        // Set processing state
        btn.dataset.queueState = 'processing';
        btn.dataset.originalText = btn.textContent;
        btn.textContent = 'Queueing...';
        btn.classList.add('queue-processing');
        btn.disabled = true;

        console.log('[TaskScheduler] Triggering', tabName, 'Generate button');

        // Function to reset button state
        const resetButton = (message) => {
            btn.dataset.queueState = '';
            btn.textContent = btn.dataset.originalText || 'Queue';
            btn.classList.remove('queue-processing');
            btn.disabled = false;
            if (message) {
                console.log('[TaskScheduler]', message);
            }
        };

        // Function to check intercept status
        const checkStatus = () => {
            fetch('/task-scheduler/intercept/status')
                .then(r => r.json())
                .then(data => {
                    if (!data.success) {
                        resetButton('Status check failed: ' + data.error);
                        return;
                    }

                    if (data.timed_out) {
                        resetButton('Queue timed out - please try again');
                        // Show notification
                        if (typeof gradio_config !== 'undefined') {
                            console.warn('[TaskScheduler] Queue operation timed out');
                        }
                        return;
                    }

                    if (!data.is_active) {
                        // Intercept completed (either success or cleared)
                        if (data.last_result) {
                            resetButton('Queued: ' + data.last_result);
                        } else {
                            resetButton('Queue completed');
                        }
                        return;
                    }

                    // Still active, check again
                    if (data.remaining_seconds !== null && data.remaining_seconds > 0) {
                        setTimeout(checkStatus, 500);
                    } else {
                        resetButton('Queue status unknown');
                    }
                })
                .catch(err => {
                    console.error('[TaskScheduler] Status check error:', err);
                    resetButton('Error checking status');
                });
        };

        // Trigger Generate button after a short delay
        setTimeout(() => {
            if (generateBtn) {
                generateBtn.click();
                // Start polling for completion
                setTimeout(checkStatus, 300);
            } else {
                console.error('[TaskScheduler]', generateBtnId, 'button not found');
                resetButton('Generate button not found');
            }
        }, 100);

        return [];
    }
    """

    try:
        with demo:
            # txt2img Queue button
            if _txt2img_queue_btn:
                def queue_txt2img():
                    set_intercept_mode("txt2img")
                    print("[TaskScheduler:Interceptor] Intercept mode set for txt2img")
                    return "txt2img"

                _txt2img_queue_btn.click(
                    fn=queue_txt2img,
                    inputs=[],
                    outputs=[],
                    _js=f"() => {{ ({queue_button_js})('txt2img'); return []; }}"
                )
                print("[TaskScheduler:Interceptor] txt2img Queue button configured")

            # img2img Queue button
            if _img2img_queue_btn:
                def queue_img2img():
                    set_intercept_mode("img2img")
                    print("[TaskScheduler:Interceptor] Intercept mode set for img2img")
                    return "img2img"

                _img2img_queue_btn.click(
                    fn=queue_img2img,
                    inputs=[],
                    outputs=[],
                    _js=f"() => {{ ({queue_button_js})('img2img'); return []; }}"
                )
                print("[TaskScheduler:Interceptor] img2img Queue button configured")

            print("[TaskScheduler:Interceptor] Queue buttons setup complete")
    except Exception as e:
        print(f"[TaskScheduler:Interceptor] Error in setup: {e}")
        import traceback
        traceback.print_exc()
