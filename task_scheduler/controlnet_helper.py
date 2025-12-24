"""
ControlNet serialization/deserialization helper.

Handles converting ControlNetUnit objects to/from JSON-serializable dicts.
"""
import base64
from io import BytesIO
from typing import Any, Dict, List, Optional
import numpy as np


def is_controlnet_unit(obj) -> bool:
    """Check if an object is a ControlNetUnit instance."""
    return type(obj).__name__ == 'ControlNetUnit'


def serialize_controlnet_unit(unit) -> Optional[Dict[str, Any]]:
    """
    Serialize a ControlNetUnit to a JSON-serializable dict.

    Args:
        unit: A ControlNetUnit instance

    Returns:
        A dict that can be JSON-serialized, or None if serialization fails
    """
    if not is_controlnet_unit(unit):
        return None

    try:
        from dataclasses import fields

        result = {}
        for field in fields(unit):
            value = getattr(unit, field.name)

            # Skip None values
            if value is None:
                continue

            # Handle numpy arrays (images) - encode as base64
            if isinstance(value, np.ndarray):
                # For images, we'll skip them for now as they're large
                # User would need to re-configure ControlNet images
                # In the future, we could save to temp files
                result[field.name] = None
                continue

            # Handle Enum types - convert to string value
            if hasattr(value, 'value'):
                result[field.name] = value.value
                continue

            # Handle GradioImageMaskPair (dict with numpy arrays)
            if isinstance(value, dict):
                # Check if it contains numpy arrays
                has_numpy = any(isinstance(v, np.ndarray) for v in value.values())
                if has_numpy:
                    result[field.name] = None
                    continue
                result[field.name] = value
                continue

            # Handle lists
            if isinstance(value, list):
                # Check if list contains non-serializable items
                serializable_list = []
                for item in value:
                    if isinstance(item, np.ndarray):
                        serializable_list.append(None)
                    elif hasattr(item, 'value'):
                        serializable_list.append(item.value)
                    else:
                        serializable_list.append(item)
                result[field.name] = serializable_list
                continue

            # Simple types (str, int, float, bool)
            result[field.name] = value

        # Mark as serialized ControlNet unit
        result['_is_controlnet_unit'] = True

        return result

    except Exception as e:
        print(f"[TaskScheduler:ControlNet] Failed to serialize unit: {e}")
        return None


def deserialize_controlnet_unit(data: Dict[str, Any]):
    """
    Deserialize a dict back to a ControlNetUnit.

    Args:
        data: A dict previously created by serialize_controlnet_unit

    Returns:
        A ControlNetUnit instance, or None if deserialization fails
    """
    if not isinstance(data, dict):
        return None

    if not data.get('_is_controlnet_unit'):
        return None

    try:
        # Import ControlNetUnit
        from lib_controlnet.external_code import ControlNetUnit

        # Remove our marker
        clean_data = {k: v for k, v in data.items() if k != '_is_controlnet_unit'}

        # Use the built-in from_dict method
        unit = ControlNetUnit.from_dict(clean_data)

        return unit

    except ImportError:
        print("[TaskScheduler:ControlNet] ControlNet extension not available")
        return None
    except Exception as e:
        print(f"[TaskScheduler:ControlNet] Failed to deserialize unit: {e}")
        return None


def serialize_script_arg(arg) -> Any:
    """
    Serialize a single script argument, handling ControlNetUnit specially.

    Args:
        arg: Any script argument

    Returns:
        A JSON-serializable version of the argument
    """
    if is_controlnet_unit(arg):
        return serialize_controlnet_unit(arg)

    # Handle lists that might contain ControlNetUnit
    if isinstance(arg, (list, tuple)):
        result = []
        for item in arg:
            if is_controlnet_unit(item):
                serialized = serialize_controlnet_unit(item)
                result.append(serialized)
            else:
                result.append(item)
        return result

    return arg


def deserialize_script_arg(arg) -> Any:
    """
    Deserialize a single script argument, handling ControlNetUnit specially.

    Args:
        arg: A script argument that may have been serialized

    Returns:
        The deserialized argument
    """
    # Check if it's a serialized ControlNetUnit
    if isinstance(arg, dict) and arg.get('_is_controlnet_unit'):
        return deserialize_controlnet_unit(arg)

    # Handle lists that might contain serialized ControlNetUnit
    if isinstance(arg, list):
        result = []
        for item in arg:
            if isinstance(item, dict) and item.get('_is_controlnet_unit'):
                unit = deserialize_controlnet_unit(item)
                result.append(unit if unit is not None else item)
            else:
                result.append(item)
        return result

    return arg


def deserialize_controlnet_args(script_args: List[Any], controlnet_arg_indices: Optional[set] = None) -> List[Any]:
    """
    Deserialize ControlNet arguments in a script_args list.

    Args:
        script_args: The full script_args list
        controlnet_arg_indices: Optional set of indices where ControlNet args are

    Returns:
        script_args with ControlNet units deserialized
    """
    if not script_args:
        return script_args

    result = list(script_args)

    for i, arg in enumerate(result):
        # If we know the ControlNet indices, only process those
        if controlnet_arg_indices is not None and i not in controlnet_arg_indices:
            continue

        result[i] = deserialize_script_arg(arg)

    return result
