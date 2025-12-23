"""
Interceptor Method for Task Scheduler.

This method uses the interceptor pattern:
1. Queue button click sets intercept mode via API
2. JavaScript triggers the Generate button
3. The AlwaysOn script (queue_interceptor.py) intercepts in before_process
4. Captures ALL parameters from StableDiffusionProcessing object
5. Queues the task and aborts generation

This is the same approach used by Agent Scheduler.
"""
from .queue_handler import (
    setup_queue_buttons,
    on_after_component,
)

__all__ = ['setup_queue_buttons', 'on_after_component']
