"""
Schema definitions and validation for parameter capture/restore.

Defines the expected structure of data returned by param handlers,
with recursive validation support for nested fields.
"""
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Dict, Optional, Union, get_type_hints, get_origin, get_args


class SkipNested:
    """
    Marker type for fields where we validate key exists but skip content validation.
    Use this for dynamic/variable structure fields like script_args.
    """
    pass


def validate_schema(data: Dict[str, Any], schema_cls, path: str = "") -> None:
    """
    Validate a dict against a dataclass schema.

    Rules:
    - All fields defined in schema must exist as keys in data
    - Fields typed as SkipNested: only check key exists, skip content validation
    - Fields typed as another dataclass: recursively validate
    - Optional[X] fields: if value is None, skip nested validation; otherwise validate as X
    - All other fields: just check key exists

    Args:
        data: The dict to validate
        schema_cls: A dataclass defining the expected structure
        path: Current path for error messages (used in recursion)

    Raises:
        TypeError: If schema_cls is not a dataclass
        ValueError: If validation fails (missing fields, wrong structure)
    """
    if not is_dataclass(schema_cls):
        raise TypeError(f"{schema_cls} must be a dataclass")

    if not isinstance(data, dict):
        raise ValueError(f"{path or 'data'} must be a dict, got {type(data).__name__}")

    hints = get_type_hints(schema_cls)

    for field_name, field_type in hints.items():
        field_path = f"{path}.{field_name}" if path else field_name

        # Check field exists in data
        if field_name not in data:
            raise ValueError(f"Missing required field: {field_path}")

        value = data[field_name]

        # Skip nested validation if marked with SkipNested
        if field_type is SkipNested:
            continue

        # Handle Optional[X] - unwrap to get inner type
        origin = get_origin(field_type)
        inner_type = field_type

        if origin is Union:
            args = get_args(field_type)
            # Check if it's Optional (Union with None)
            if type(None) in args:
                # If value is None, skip further validation
                if value is None:
                    continue
                # Get the non-None type for further validation
                non_none_types = [a for a in args if a is not type(None)]
                if len(non_none_types) == 1:
                    inner_type = non_none_types[0]

        # Recursively validate nested dataclass schemas
        if is_dataclass(inner_type):
            if value is None:
                # None is acceptable only if the original type was Optional
                if origin is not Union or type(None) not in get_args(field_type):
                    raise ValueError(f"Field {field_path} cannot be None (not Optional)")
            else:
                if not isinstance(value, dict):
                    raise ValueError(
                        f"Field {field_path} must be a dict for nested schema, "
                        f"got {type(value).__name__}"
                    )
                validate_schema(value, inner_type, field_path)


# =============================================================================
# Display Info Schema - Used by API to show task details
# =============================================================================

@dataclass
class DisplayInfoSchema:
    """
    Schema for display info returned by extract_display_info().
    All param handlers must return a dict matching this structure.
    """
    # Core display fields
    vae: Any  # str, can be empty
    sampler_name: Any
    scheduler: Any
    width: Any
    height: Any

    # Hires fix
    enable_hr: Any
    upscaled_width: Any
    upscaled_height: Any

    # Batch info
    batch_size: Any
    n_iter: Any


# =============================================================================
# Captured Params Schema - Structure of params stored in database
# =============================================================================

@dataclass
class UiSettingsSchema:
    """Schema for ui_settings nested field."""
    # These are optional - not all may be present
    # Using SkipNested because the actual fields vary based on user's quicksettings
    pass  # Empty - we just validate ui_settings key exists, content is variable


@dataclass
class CapturedParamsSchema:
    """
    Schema for the full params dict captured and stored in database.
    Defines the expected structure that both legacy and dynamic capture must produce.
    """
    # Core generation params
    prompt: Any
    negative_prompt: Any
    width: Any
    height: Any
    steps: Any
    cfg_scale: Any
    seed: Any
    sampler_name: Any

    # Optional nested structures - validate key exists but not contents
    # because these have variable structure
    ui_settings: SkipNested
    override_settings: SkipNested
    extra_generation_params: SkipNested

    # Script args - variable structure
    _script_args_labeled: SkipNested


def validate_display_info(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate display info dict against DisplayInfoSchema.

    Args:
        data: Dict returned by extract_display_info()

    Returns:
        The validated data (unchanged if valid)

    Raises:
        ValueError: If validation fails
    """
    validate_schema(data, DisplayInfoSchema)
    return data


def validate_captured_params(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate captured params dict against CapturedParamsSchema.

    Note: This is a loose validation - many fields are optional or variable.
    The schema ensures core required fields are present.

    Args:
        data: Dict returned by capture()

    Returns:
        The validated data (unchanged if valid)

    Raises:
        ValueError: If validation fails
    """
    validate_schema(data, CapturedParamsSchema)
    return data
