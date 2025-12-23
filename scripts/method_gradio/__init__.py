"""
Gradio Binding Method for Task Scheduler.

This method creates Queue buttons via Gradio and binds them to receive
the same inputs as the Generate buttons. Captures UI component values directly.
"""
from .queue_handler import (
    setup_queue_buttons,
    bind_queue_buttons,
    on_after_component,
)

__all__ = ['setup_queue_buttons', 'bind_queue_buttons', 'on_after_component']
