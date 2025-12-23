"""
Gradio Binding Method - Queue Handler

This method creates Queue buttons via Gradio and binds them to receive
the same inputs as the Generate buttons. Captures UI component values directly.

Pros:
- No fake generation start
- Direct Gradio integration

Cons:
- May not capture all parameters (VAE, Clip Skip from shared.opts)
- Difficult to map raw values back to named parameters
"""
import gradio as gr
from typing import Optional, List, Any
import json
import os
import sys

# Add parent directories to path for imports
scripts_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ext_dir = os.path.dirname(scripts_dir)
if ext_dir not in sys.path:
    sys.path.insert(0, ext_dir)
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from modules import shared
from task_scheduler.models import TaskType
from task_scheduler.queue_manager import get_queue_manager


# Global references to UI components
_txt2img_queue_btn: Optional[gr.Button] = None
_img2img_queue_btn: Optional[gr.Button] = None
_txt2img_generate_btn: Optional[gr.Button] = None
_img2img_generate_btn: Optional[gr.Button] = None

# Store input component names for each tab
_txt2img_input_names: List[str] = []
_img2img_input_names: List[str] = []


def get_current_checkpoint() -> str:
    """Get the currently selected checkpoint model."""
    try:
        return shared.opts.sd_model_checkpoint or ""
    except Exception:
        return ""


def serialize_args_for_queue(args: tuple, input_names: List[str], is_img2img: bool = False) -> list:
    """
    Serialize Gradio arguments for storage in the queue.
    Returns a list of dicts with 'name' and 'value' for each argument.
    """
    serialized = []
    for i, arg in enumerate(args):
        name = input_names[i] if i < len(input_names) else f"arg_{i}"

        try:
            json.dumps(arg)
            value = arg
        except (TypeError, ValueError):
            if hasattr(arg, 'save'):  # PIL Image
                import base64
                from io import BytesIO
                buffer = BytesIO()
                arg.save(buffer, format='PNG')
                img_str = base64.b64encode(buffer.getvalue()).decode()
                value = {"__type__": "image", "data": img_str}
            elif hasattr(arg, 'value'):
                value = arg.value
            elif arg is None:
                value = None
            else:
                value = {"__type__": "str", "data": str(arg)}

        serialized.append({"name": name, "value": value})

    return serialized


def queue_from_ui_args(is_img2img: bool, *args):
    """
    Queue a task from Gradio UI arguments.
    This receives ALL the same args as the Generate button.
    """
    global _txt2img_input_names, _img2img_input_names

    print(f"[TaskScheduler:Gradio] queue_from_ui_args called with {len(args)} arguments")

    try:
        queue_manager = get_queue_manager()
        task_type = TaskType.IMG2IMG if is_img2img else TaskType.TXT2IMG
        checkpoint = get_current_checkpoint()
        input_names = _img2img_input_names if is_img2img else _txt2img_input_names
        serialized_args = serialize_args_for_queue(args, input_names, is_img2img)

        params = {}
        if len(args) > 0 and isinstance(args[0], str):
            params["prompt"] = args[0]
        if len(args) > 1 and isinstance(args[1], str):
            params["negative_prompt"] = args[1]

        # Capture settings from shared.opts
        try:
            params["sd_vae"] = shared.opts.sd_vae
            params["CLIP_stop_at_last_layers"] = shared.opts.CLIP_stop_at_last_layers
            params["sd_model_checkpoint"] = shared.opts.sd_model_checkpoint
            if hasattr(shared.opts, 'eta_noise_seed_delta'):
                params["eta_noise_seed_delta"] = shared.opts.eta_noise_seed_delta
        except Exception as e:
            print(f"[TaskScheduler:Gradio] Could not capture some shared.opts: {e}")

        task = queue_manager.add_task(
            task_type=task_type,
            params=params,
            checkpoint=checkpoint,
            script_args=serialized_args,
            name=""
        )

        result_msg = f"Task queued: {task.get_display_name()}"
        print(f"[TaskScheduler:Gradio] {result_msg}")
        print(f"[TaskScheduler:Gradio] Captured {len(serialized_args)} arguments")
        gr.Info(result_msg)

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"Error queuing task: {str(e)}"
        print(f"[TaskScheduler:Gradio] {error_msg}")
        gr.Warning(error_msg)


def get_component_name(component, debug_first: bool = False) -> str:
    """Extract a name from a Gradio component (elem_id or label)."""
    if debug_first:
        print(f"[TaskScheduler:Gradio] Component type: {type(component)}")
        print(f"[TaskScheduler:Gradio] Component attributes: {[a for a in dir(component) if not a.startswith('_')]}")
        for attr in ['elem_id', 'label', 'elem_classes', 'info', 'key']:
            val = getattr(component, attr, 'NOT_FOUND')
            print(f"[TaskScheduler:Gradio]   {attr}: {val}")

    if hasattr(component, 'elem_id') and component.elem_id:
        return str(component.elem_id)
    if hasattr(component, 'label') and component.label:
        return str(component.label)
    if hasattr(component, 'key') and component.key:
        return str(component.key)

    class_name = component.__class__.__name__
    comp_id = getattr(component, '_id', 'unknown')
    return f"{class_name}_{comp_id}"


def find_generate_fn_by_name(demo, fn_name: str):
    """Find the generation function by name."""
    print(f"[TaskScheduler:Gradio] Looking for fn with name: {fn_name}")

    if not hasattr(demo, 'fns') or not demo.fns:
        print(f"[TaskScheduler:Gradio] demo.fns not available")
        return None

    if hasattr(demo.fns, 'values'):
        fns_list = list(demo.fns.values())
    else:
        fns_list = list(demo.fns)

    print(f"[TaskScheduler:Gradio] Searching through {len(fns_list)} fns...")

    candidates = []
    for i, fn in enumerate(fns_list):
        fn_func = getattr(fn, 'fn', None)
        if fn_func is None:
            continue

        actual_name = None
        if hasattr(fn_func, '__name__'):
            actual_name = fn_func.__name__
        elif callable(fn_func):
            actual_name = str(fn_func)

        if actual_name == fn_name:
            fn_inputs = getattr(fn, 'inputs', [])
            fn_outputs = getattr(fn, 'outputs', [])
            input_count = len(fn_inputs) if fn_inputs else 0
            output_count = len(fn_outputs) if fn_outputs else 0

            print(f"[TaskScheduler:Gradio] Found fn '{fn_name}' at index {i}: inputs={input_count}, outputs={output_count}")

            if output_count >= 4:
                candidates.append({
                    'inputs': list(fn_inputs) if fn_inputs else [],
                    'outputs': list(fn_outputs) if fn_outputs else [],
                    'name': fn_name,
                    'input_count': input_count
                })

    if not candidates:
        print(f"[TaskScheduler:Gradio] No fn found with name '{fn_name}'")
        return None

    best = max(candidates, key=lambda x: x['input_count'])
    print(f"[TaskScheduler:Gradio] Selected fn with {best['input_count']} inputs")
    return best


def find_generate_dependency(demo, generate_btn):
    """Find the dependency for a generate button."""
    btn_id = generate_btn._id
    elem_id = getattr(generate_btn, 'elem_id', None)

    print(f"[TaskScheduler:Gradio] Looking for dependency for button ID: {btn_id}, elem_id: {elem_id}")

    if elem_id == "txt2img_generate":
        return find_generate_fn_by_name(demo, "txt2img")
    elif elem_id == "img2img_generate":
        return find_generate_fn_by_name(demo, "img2img")

    print(f"[TaskScheduler:Gradio] Could not find dependency for button {btn_id}")
    return None


def on_after_component(component, **kwargs):
    """Detect Generate buttons and create Queue buttons next to them."""
    global _txt2img_generate_btn, _img2img_generate_btn
    global _txt2img_queue_btn, _img2img_queue_btn

    elem_id = kwargs.get("elem_id", "")

    if elem_id == "txt2img_generate":
        _txt2img_generate_btn = component
        print(f"[TaskScheduler:Gradio] Found txt2img_generate button: {component._id}")
        _txt2img_queue_btn = gr.Button(
            "Queue",
            variant="secondary",
            elem_id="txt2img_queue",
            min_width=60
        )
        print(f"[TaskScheduler:Gradio] Created txt2img Queue button: {_txt2img_queue_btn._id}")

    elif elem_id == "img2img_generate":
        _img2img_generate_btn = component
        print(f"[TaskScheduler:Gradio] Found img2img_generate button: {component._id}")
        _img2img_queue_btn = gr.Button(
            "Queue",
            variant="secondary",
            elem_id="img2img_queue",
            min_width=60
        )
        print(f"[TaskScheduler:Gradio] Created img2img Queue button: {_img2img_queue_btn._id}")


def bind_queue_buttons(demo):
    """Bind Queue buttons to receive the same inputs as Generate buttons."""
    global _txt2img_queue_btn, _img2img_queue_btn
    global _txt2img_input_names, _img2img_input_names

    print("[TaskScheduler:Gradio] Binding Queue buttons...")

    # txt2img
    if _txt2img_generate_btn:
        txt2img_dep = find_generate_dependency(demo, _txt2img_generate_btn)
        if txt2img_dep:
            inputs = txt2img_dep.get("inputs", [])
            print(f"[TaskScheduler:Gradio] Found txt2img dependency with {len(inputs)} inputs")

            _txt2img_input_names = []
            for i, comp in enumerate(inputs):
                name = get_component_name(comp, debug_first=(i == 0))
                _txt2img_input_names.append(name)
            print(f"[TaskScheduler:Gradio] Extracted {len(_txt2img_input_names)} input names")
            print(f"[TaskScheduler:Gradio] First 10 names: {_txt2img_input_names[:10]}")

            def queue_txt2img(*args):
                queue_from_ui_args(False, *args)

            if _txt2img_queue_btn:
                try:
                    _txt2img_queue_btn.click(fn=queue_txt2img, inputs=inputs, outputs=[])
                    print(f"[TaskScheduler:Gradio] txt2img Queue button bound with {len(inputs)} inputs")
                except Exception as e:
                    print(f"[TaskScheduler:Gradio] Error binding txt2img: {e}")
                    import traceback
                    traceback.print_exc()

    # img2img
    if _img2img_generate_btn:
        img2img_dep = find_generate_dependency(demo, _img2img_generate_btn)
        if img2img_dep:
            inputs = img2img_dep.get("inputs", [])
            print(f"[TaskScheduler:Gradio] Found img2img dependency with {len(inputs)} inputs")

            _img2img_input_names = [get_component_name(comp) for comp in inputs]

            def queue_img2img(*args):
                queue_from_ui_args(True, *args)

            if _img2img_queue_btn:
                try:
                    _img2img_queue_btn.click(fn=queue_img2img, inputs=inputs, outputs=[])
                    print(f"[TaskScheduler:Gradio] img2img Queue button bound with {len(inputs)} inputs")
                except Exception as e:
                    print(f"[TaskScheduler:Gradio] Error binding img2img: {e}")
                    import traceback
                    traceback.print_exc()


def setup_queue_buttons(demo):
    """Setup function called from main UI script."""
    try:
        with demo:
            bind_queue_buttons(demo)
    except Exception as e:
        print(f"[TaskScheduler:Gradio] Error in setup: {e}")
        import traceback
        traceback.print_exc()
