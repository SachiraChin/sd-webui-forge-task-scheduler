"""
Parameter capture and restoration module.

Provides two approaches:
1. Legacy: Uses hardcoded field names (stable, tested)
2. Dynamic: Captures all serializable attributes (future-proof)
"""
from typing import Optional

from .base import BaseParameterCapture, BaseParameterRestore
from .legacy import LegacyParameterCapture, LegacyParameterRestore
from .dynamic import DynamicParameterCapture, DynamicParameterRestore
from .schema import (
    DisplayInfoSchema,
    SkipNested,
    validate_schema,
    validate_display_info,
)


def get_capture_strategy(use_dynamic: bool = False) -> BaseParameterCapture:
    """
    Get the appropriate capture strategy.

    Args:
        use_dynamic: If True, use DynamicParameterCapture. Otherwise use LegacyParameterCapture.

    Returns:
        A parameter capture instance.
    """
    if use_dynamic:
        return DynamicParameterCapture()
    return LegacyParameterCapture()


def get_restore_strategy(capture_format: Optional[str]) -> BaseParameterRestore:
    """
    Get the appropriate restore strategy based on capture format.

    Args:
        capture_format: The capture format from the task (None=legacy, "dynamic"=dynamic).

    Returns:
        A parameter restore instance.
    """
    if capture_format == "dynamic":
        return DynamicParameterRestore()
    return LegacyParameterRestore()


__all__ = [
    "BaseParameterCapture",
    "BaseParameterRestore",
    "LegacyParameterCapture",
    "LegacyParameterRestore",
    "DynamicParameterCapture",
    "DynamicParameterRestore",
    "get_capture_strategy",
    "get_restore_strategy",
    "DisplayInfoSchema",
    "SkipNested",
    "validate_schema",
    "validate_display_info",
]
