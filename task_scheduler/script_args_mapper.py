"""
Script Args Mapper - Maps script_args indices to field names.

This is a plugin module that extracts field names from registered scripts
by inspecting their UI components. It can be used to add labels to the
raw script_args values captured by the interceptor method.

Usage:
    from task_scheduler.script_args_mapper import get_cached_mapping

    # Get the mapping for current scripts
    mapping = get_cached_mapping()
"""

# Lazy imports to avoid loading modules.scripts too early
_scripts_module = None


def _get_scripts():
    """Lazy load the scripts module."""
    global _scripts_module
    if _scripts_module is None:
        try:
            from modules import scripts
            _scripts_module = scripts
        except ImportError:
            pass
    return _scripts_module


def get_script_args_mapping():
    """
    Build a mapping of script_args indices to field information.

    Returns a dict like:
    {
        0: {"name": "txt2img_prompt", "label": "Prompt", "script": None, "type": "Textbox"},
        1: {"name": "txt2img_neg_prompt", "label": "Negative prompt", "script": None, "type": "Textbox"},
        ...
        50: {"name": "adetailer_enable", "label": "Enable ADetailer", "script": "ADetailer", "type": "Checkbox"},
        ...
    }
    """
    mapping = {}
    scripts = _get_scripts()

    if scripts is None:
        print("[TaskScheduler:Mapper] modules.scripts not available")
        return mapping

    try:
        # Get the script runner for txt2img (similar structure for img2img)
        script_runner = scripts.scripts_txt2img
        if script_runner is None:
            print("[TaskScheduler:Mapper] scripts_txt2img not available")
            return mapping

        print(f"[TaskScheduler:Mapper] Found {len(script_runner.scripts)} scripts")

        # Iterate through all registered scripts
        for script in script_runner.scripts:
            script_name = getattr(script, 'title', lambda: script.__class__.__name__)()
            args_from = getattr(script, 'args_from', None)
            args_to = getattr(script, 'args_to', None)

            if args_from is None or args_to is None:
                continue

            print(f"[TaskScheduler:Mapper] Script '{script_name}': args [{args_from}:{args_to}]")

            # Try to get UI components for this script
            # The UI components are stored after ui() is called
            ui_components = []

            # Check if script has stored UI components
            if hasattr(script, 'ui_components'):
                ui_components = script.ui_components
            elif hasattr(script, 'infotext_fields'):
                # Some scripts store field info here
                for field_info in script.infotext_fields:
                    if hasattr(field_info, '__iter__') and len(field_info) >= 2:
                        component, name = field_info[0], field_info[1]
                        ui_components.append((component, name))

            # Map each argument index to its info
            for idx in range(args_from, args_to):
                relative_idx = idx - args_from

                info = {
                    "index": idx,
                    "script": script_name,
                    "name": f"{script_name.lower().replace(' ', '_')}_{relative_idx}",
                    "label": f"{script_name} arg {relative_idx}",
                    "type": "unknown"
                }

                # Try to get actual component info
                if relative_idx < len(ui_components):
                    component = ui_components[relative_idx]
                    if hasattr(component, 'elem_id') and component.elem_id:
                        info["name"] = component.elem_id
                    if hasattr(component, 'label') and component.label:
                        info["label"] = component.label
                    info["type"] = component.__class__.__name__

                mapping[idx] = info

        print(f"[TaskScheduler:Mapper] Built mapping for {len(mapping)} arguments")

    except Exception as e:
        print(f"[TaskScheduler:Mapper] Error building mapping: {e}")
        import traceback
        traceback.print_exc()

    return mapping


def map_script_args(script_args, mapping=None):
    """
    Convert raw script_args list to a labeled list with field information.

    Args:
        script_args: List of raw argument values
        mapping: Optional pre-built mapping (will build if not provided)

    Returns:
        List of dicts with 'index', 'name', 'label', 'script', 'type', 'value'
    """
    if mapping is None:
        mapping = get_script_args_mapping()

    result = []
    for idx, value in enumerate(script_args):
        if idx in mapping:
            entry = mapping[idx].copy()
            entry["value"] = value
        else:
            entry = {
                "index": idx,
                "name": f"arg_{idx}",
                "label": f"Argument {idx}",
                "script": None,
                "type": "unknown",
                "value": value
            }
        result.append(entry)

    return result


# Cache the mapping to avoid rebuilding on every call
_cached_mapping = None
_mapping_built = False


def get_cached_mapping():
    """Get or build the cached mapping."""
    global _cached_mapping, _mapping_built

    if not _mapping_built:
        _cached_mapping = get_script_args_mapping()
        _mapping_built = True

    return _cached_mapping


def invalidate_mapping_cache():
    """Invalidate the cached mapping (call when scripts change)."""
    global _cached_mapping, _mapping_built
    _cached_mapping = None
    _mapping_built = False
