"""
Script Args Serializer - Handles serialization/deserialization of script_args.

Properly handles ControlNetUnit and other complex objects that need special
treatment when storing to/loading from the database.
"""
import json
from dataclasses import is_dataclass, asdict
from typing import Any, List
import numpy as np


def _is_controlnet_unit(obj) -> bool:
    """Check if an object is a ControlNetUnit."""
    return type(obj).__name__ == 'ControlNetUnit'


def _is_controlnet_unit_dict(d: dict) -> bool:
    """Check if a dict looks like a serialized ControlNetUnit."""
    if not isinstance(d, dict):
        return False
    # ControlNetUnit has these characteristic fields
    cn_fields = {'enabled', 'module', 'model', 'weight'}
    return cn_fields.issubset(d.keys())


def _serialize_value(value: Any) -> Any:
    """Serialize a single value for JSON storage."""
    if value is None:
        return None

    # Handle ControlNetUnit
    if _is_controlnet_unit(value):
        # Convert to dict, marking it as a ControlNetUnit
        try:
            d = asdict(value)
            d['__type__'] = 'ControlNetUnit'
            # Handle numpy arrays in the dict
            return _serialize_value(d)
        except Exception as e:
            print(f"[TaskScheduler:Serializer] Error serializing ControlNetUnit: {e}")
            return None

    # Handle numpy arrays
    if isinstance(value, np.ndarray):
        # Skip image data - too large and not needed for most cases
        if value.ndim >= 2:
            return None
        return value.tolist()

    # Handle dicts recursively
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}

    # Handle lists/tuples recursively
    if isinstance(value, (list, tuple)):
        serialized = [_serialize_value(v) for v in value]
        return serialized

    # Handle other dataclasses
    if is_dataclass(value) and not isinstance(value, type):
        try:
            d = asdict(value)
            d['__type__'] = type(value).__name__
            return _serialize_value(d)
        except Exception:
            return str(value)

    # Handle enums
    if hasattr(value, 'value'):
        return value.value

    # Basic JSON-serializable types
    if isinstance(value, (str, int, float, bool)):
        return value

    # Fallback to string representation
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _deserialize_value(value: Any) -> Any:
    """Deserialize a single value from JSON storage."""
    if value is None:
        return None

    # Handle dicts that might be ControlNetUnit
    if isinstance(value, dict):
        type_marker = value.get('__type__')

        if type_marker == 'ControlNetUnit' or _is_controlnet_unit_dict(value):
            try:
                # Remove type marker before creating unit
                clean_dict = {k: v for k, v in value.items() if k != '__type__'}
                # Import ControlNetUnit lazily
                from lib_controlnet.external_code import ControlNetUnit
                unit = ControlNetUnit.from_dict(clean_dict)
                return unit
            except ImportError:
                print("[TaskScheduler:Serializer] ControlNet not available")
                return value
            except Exception as e:
                print(f"[TaskScheduler:Serializer] Error deserializing ControlNetUnit: {e}")
                import traceback
                traceback.print_exc()
                return value

        # Recursively deserialize dict values
        return {k: _deserialize_value(v) for k, v in value.items()}

    # Handle lists recursively
    if isinstance(value, list):
        return [_deserialize_value(v) for v in value]

    return value


def serialize_script_args(script_args: List[Any]) -> str:
    """
    Serialize script_args list to JSON string.

    Properly handles ControlNetUnit and other complex objects.

    Args:
        script_args: List of script arguments

    Returns:
        JSON string representation
    """
    serialized = [_serialize_value(arg) for arg in script_args]
    return json.dumps(serialized)


def deserialize_script_args(json_str: str) -> List[Any]:
    """
    Deserialize script_args from JSON string.

    Reconstructs ControlNetUnit and other complex objects.

    Args:
        json_str: JSON string from database

    Returns:
        List of script arguments with proper types
    """
    if not json_str:
        return []

    try:
        data = json.loads(json_str)
        if not isinstance(data, list):
            return []
        return [_deserialize_value(arg) for arg in data]
    except json.JSONDecodeError as e:
        print(f"[TaskScheduler:Serializer] JSON decode error: {e}")
        return []
