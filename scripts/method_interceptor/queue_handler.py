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
    """
    global _txt2img_queue_btn, _img2img_queue_btn

    print("[TaskScheduler:Interceptor] Setting up Queue buttons...")

    try:
        with demo:
            # txt2img Queue button - use _js to trigger Generate after Python sets intercept mode
            if _txt2img_queue_btn:
                def queue_txt2img():
                    set_intercept_mode("txt2img")
                    print("[TaskScheduler:Interceptor] Intercept mode set for txt2img")

                _txt2img_queue_btn.click(
                    fn=queue_txt2img,
                    inputs=[],
                    outputs=[],
                    _js="""
                    () => {
                        console.log('[TaskScheduler:Interceptor] Triggering txt2img Generate button');
                        setTimeout(() => {
                            const generateBtn = document.getElementById('txt2img_generate');
                            if (generateBtn) {
                                generateBtn.click();
                            } else {
                                console.error('[TaskScheduler:Interceptor] txt2img_generate button not found');
                            }
                        }, 100);
                        return [];
                    }
                    """
                )
                print("[TaskScheduler:Interceptor] txt2img Queue button configured")

            # img2img Queue button
            if _img2img_queue_btn:
                def queue_img2img():
                    set_intercept_mode("img2img")
                    print("[TaskScheduler:Interceptor] Intercept mode set for img2img")

                _img2img_queue_btn.click(
                    fn=queue_img2img,
                    inputs=[],
                    outputs=[],
                    _js="""
                    () => {
                        console.log('[TaskScheduler:Interceptor] Triggering img2img Generate button');
                        setTimeout(() => {
                            const generateBtn = document.getElementById('img2img_generate');
                            if (generateBtn) {
                                generateBtn.click();
                            } else {
                                console.error('[TaskScheduler:Interceptor] img2img_generate button not found');
                            }
                        }, 100);
                        return [];
                    }
                    """
                )
                print("[TaskScheduler:Interceptor] img2img Queue button configured")

            print("[TaskScheduler:Interceptor] Queue buttons setup complete")
    except Exception as e:
        print(f"[TaskScheduler:Interceptor] Error in setup: {e}")
        import traceback
        traceback.print_exc()
