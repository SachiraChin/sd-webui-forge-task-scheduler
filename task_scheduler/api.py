"""
FastAPI endpoints for Task Scheduler.
Provides REST API for queue operations.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Any
import traceback

from .models import Task, TaskStatus, TaskType
from .queue_manager import get_queue_manager
from .executor import get_executor

# Import intercept functions from the script
def get_intercept_functions():
    """Get intercept functions from the queue_interceptor script."""
    try:
        import sys
        import os
        ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        scripts_dir = os.path.join(ext_dir, "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from queue_interceptor import set_intercept_mode, get_intercept_result, clear_intercept_mode
        return set_intercept_mode, get_intercept_result, clear_intercept_mode
    except Exception as e:
        print(f"[TaskScheduler] Failed to import intercept functions: {e}")
        return None, None, None


class QueueTaskRequest(BaseModel):
    """Request body for queuing a task."""
    prompt: str = ""
    negative_prompt: str = ""
    steps: int = 20
    cfg_scale: float = 7.0
    width: int = 512
    height: int = 512
    batch_size: int = 1
    n_iter: int = 1
    seed: int = -1
    sampler_name: str = "Euler"
    scheduler: str = "automatic"
    # Additional parameters can be added as needed
    extra_params: dict = {}


class TaskResponse(BaseModel):
    """Response containing task info."""
    id: str
    task_type: str
    status: str
    name: str
    checkpoint: str
    created_at: str


def setup_api(app: FastAPI):
    """Register API endpoints with the FastAPI app."""

    @app.post("/task-scheduler/queue/txt2img")
    async def queue_txt2img(request: QueueTaskRequest):
        """Queue a txt2img task."""
        try:
            queue_manager = get_queue_manager()

            # Get current checkpoint
            try:
                from modules import shared
                checkpoint = shared.opts.sd_model_checkpoint or ""
            except Exception:
                checkpoint = ""

            # Build params dict
            params = {
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "steps": request.steps,
                "cfg_scale": request.cfg_scale,
                "width": request.width,
                "height": request.height,
                "batch_size": request.batch_size,
                "n_iter": request.n_iter,
                "seed": request.seed,
                "sampler_name": request.sampler_name,
                "scheduler": request.scheduler,
                **request.extra_params
            }

            # Debug logging
            print(f"[TaskScheduler] Queuing txt2img task")
            print(f"[TaskScheduler] extra_params received: {request.extra_params}")
            print(f"[TaskScheduler] Final params keys: {list(params.keys())}")
            if 'enable_hr' in params:
                print(f"[TaskScheduler] Hires.fix enabled: {params.get('enable_hr')}")

            # Create task
            task = queue_manager.add_task(
                task_type=TaskType.TXT2IMG,
                params=params,
                checkpoint=checkpoint,
                script_args=[],
                name=""
            )

            return JSONResponse({
                "success": True,
                "task_id": task.id,
                "message": f"Task queued: {task.get_display_name()}"
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/queue/img2img")
    async def queue_img2img(request: QueueTaskRequest):
        """Queue an img2img task."""
        try:
            queue_manager = get_queue_manager()

            # Get current checkpoint
            try:
                from modules import shared
                checkpoint = shared.opts.sd_model_checkpoint or ""
            except Exception:
                checkpoint = ""

            # Build params dict
            params = {
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "steps": request.steps,
                "cfg_scale": request.cfg_scale,
                "width": request.width,
                "height": request.height,
                "batch_size": request.batch_size,
                "n_iter": request.n_iter,
                "seed": request.seed,
                "sampler_name": request.sampler_name,
                "scheduler": request.scheduler,
                "denoising_strength": request.extra_params.get("denoising_strength", 0.75),
                **request.extra_params
            }

            # Create task
            task = queue_manager.add_task(
                task_type=TaskType.IMG2IMG,
                params=params,
                checkpoint=checkpoint,
                script_args=[],
                name=""
            )

            return JSONResponse({
                "success": True,
                "task_id": task.id,
                "message": f"Task queued: {task.get_display_name()}"
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.get("/task-scheduler/queue")
    async def get_queue():
        """Get all tasks in the queue."""
        try:
            from .param_capture import get_restore_strategy

            queue_manager = get_queue_manager()
            tasks = queue_manager.get_all_tasks()

            def get_task_info(t):
                # Get the appropriate restore strategy for this task's format
                restore_strategy = get_restore_strategy(t.capture_format)

                # Extract display info using the strategy (validates against schema)
                display_info = restore_strategy.extract_display_info(t.params)

                return {
                    "id": t.id,
                    "task_type": t.task_type.value,
                    "status": t.status.value,
                    "name": t.get_display_name(),
                    "checkpoint": t.get_short_checkpoint(),
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    "priority": t.priority,
                    "requeued_task_id": t.requeued_task_id,
                    # Merge display info fields
                    **display_info
                }

            return JSONResponse({
                "success": True,
                "tasks": [get_task_info(t) for t in tasks]
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.get("/task-scheduler/queue/{task_id}")
    async def get_task(task_id: str):
        """Get a specific task by ID."""
        try:
            queue_manager = get_queue_manager()
            task = queue_manager.get_task(task_id)

            if not task:
                raise HTTPException(status_code=404, detail="Task not found")

            task_dict = task.to_dict()
            print(f"[TaskScheduler] Getting task {task_id}")
            print(f"[TaskScheduler] Task params keys: {list(task.params.keys())}")
            if 'enable_hr' in task.params:
                print(f"[TaskScheduler] Task has enable_hr: {task.params.get('enable_hr')}")

            return JSONResponse({
                "success": True,
                "task": task_dict
            })

        except HTTPException:
            raise
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.delete("/task-scheduler/queue/{task_id}")
    async def delete_task(task_id: str):
        """Delete a task from the queue."""
        try:
            queue_manager = get_queue_manager()
            success = queue_manager.delete_task(task_id)

            if not success:
                raise HTTPException(status_code=404, detail="Task not found")

            return JSONResponse({
                "success": True,
                "message": "Task deleted"
            })

        except HTTPException:
            raise
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/queue/{task_id}/cancel")
    async def cancel_task(task_id: str):
        """Cancel a pending task."""
        try:
            queue_manager = get_queue_manager()
            success = queue_manager.cancel_task(task_id)

            if not success:
                return JSONResponse({
                    "success": False,
                    "error": "Task not found or not pending"
                }, status_code=400)

            return JSONResponse({
                "success": True,
                "message": "Task cancelled"
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/queue/{task_id}/retry")
    async def retry_task(task_id: str):
        """Retry a failed or cancelled task."""
        try:
            queue_manager = get_queue_manager()
            new_task = queue_manager.retry_task(task_id)

            if not new_task:
                raise HTTPException(status_code=404, detail="Task not found")

            return JSONResponse({
                "success": True,
                "task_id": new_task.id,
                "message": "Task requeued"
            })

        except HTTPException:
            raise
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/queue/{task_id}/run")
    async def run_single_task(task_id: str):
        """Run a single task immediately (without starting the full queue)."""
        try:
            executor = get_executor()

            # Check if something is already running
            if executor.is_running and executor._current_task is not None:
                return JSONResponse({
                    "success": False,
                    "error": "Another task is already running"
                }, status_code=400)

            queue_manager = get_queue_manager()
            task = queue_manager.get_task(task_id)

            if not task:
                raise HTTPException(status_code=404, detail="Task not found")

            if task.status.value != "pending":
                return JSONResponse({
                    "success": False,
                    "error": f"Task is not pending (status: {task.status.value})"
                }, status_code=400)

            # Run this single task
            executor.run_single_task(task_id)

            return JSONResponse({
                "success": True,
                "message": f"Running task: {task.get_display_name()}"
            })

        except HTTPException:
            raise
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/start")
    async def start_queue():
        """Start processing the queue."""
        try:
            executor = get_executor()
            started = executor.start()

            return JSONResponse({
                "success": True,
                "started": started,
                "message": "Queue started" if started else "Queue already running"
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/stop")
    async def stop_queue():
        """Stop processing the queue."""
        try:
            executor = get_executor()
            executor.stop()

            return JSONResponse({
                "success": True,
                "message": "Queue stopped"
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/pause")
    async def pause_queue():
        """Pause/resume the queue."""
        try:
            executor = get_executor()
            if executor.is_paused:
                executor.resume()
                message = "Queue resumed"
            else:
                executor.pause()
                message = "Queue paused"

            return JSONResponse({
                "success": True,
                "is_paused": executor.is_paused,
                "message": message
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.get("/task-scheduler/status")
    async def get_status():
        """Get queue status including button states."""
        try:
            executor = get_executor()
            status = executor.get_status()

            # Calculate button states
            is_running = status.get('is_running', False)
            is_stopping = status.get('is_stopping', False)
            is_paused = status.get('is_paused', False)
            stats = status.get('queue_stats', {})
            has_pending = stats.get('pending', 0) > 0 or stats.get('paused', 0) > 0
            has_completed = (stats.get('completed', 0) > 0 or
                           stats.get('failed', 0) > 0 or
                           stats.get('cancelled', 0) > 0 or
                           stats.get('stopped', 0) > 0)

            button_states = {
                'start': not is_running and has_pending and not is_stopping,
                'stop': is_running and not is_stopping,
                'pause': is_running and not is_stopping,
                'clear': has_completed,
            }

            return JSONResponse({
                "success": True,
                "button_states": button_states,
                **status
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/clear")
    async def clear_completed():
        """Clear completed/failed/cancelled tasks."""
        try:
            queue_manager = get_queue_manager()
            count = queue_manager.clear_completed()

            return JSONResponse({
                "success": True,
                "cleared": count,
                "message": f"Cleared {count} tasks"
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/intercept/{tab}")
    async def set_intercept(tab: str):
        """Set intercept mode for the next generation."""
        try:
            if tab not in ("txt2img", "img2img"):
                return JSONResponse({
                    "success": False,
                    "error": f"Invalid tab: {tab}"
                }, status_code=400)

            set_intercept_mode, _, _ = get_intercept_functions()
            if set_intercept_mode is None:
                return JSONResponse({
                    "success": False,
                    "error": "Intercept module not available"
                }, status_code=500)

            set_intercept_mode(tab)

            return JSONResponse({
                "success": True,
                "message": f"Intercept mode enabled for {tab}"
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.get("/task-scheduler/intercept/result")
    async def get_intercept_result_api():
        """Get the result of the last interception."""
        try:
            _, get_result, _ = get_intercept_functions()
            if get_result is None:
                return JSONResponse({
                    "success": False,
                    "error": "Intercept module not available"
                }, status_code=500)

            result = get_result()

            return JSONResponse({
                "success": True,
                "result": result
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/intercept/clear")
    async def clear_intercept():
        """Clear the intercept mode."""
        try:
            _, _, clear_mode = get_intercept_functions()
            if clear_mode is None:
                return JSONResponse({
                    "success": False,
                    "error": "Intercept module not available"
                }, status_code=500)

            clear_mode()

            return JSONResponse({
                "success": True,
                "message": "Intercept mode cleared"
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.get("/task-scheduler/settings")
    async def get_settings():
        """Get extension settings."""
        try:
            from modules import shared

            settings = {
                "enable_controlnet": getattr(shared.opts, 'task_scheduler_enable_controlnet', False),
                "large_batch_warning": getattr(shared.opts, 'task_scheduler_large_batch_warning', 1),
            }

            return JSONResponse({
                "success": True,
                "settings": settings
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.get("/task-scheduler/intercept/status")
    async def get_intercept_status():
        """Get current intercept state for UI state management."""
        try:
            _, get_result, _ = get_intercept_functions()

            # Import the state directly to get all info
            try:
                import sys
                import os
                ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                scripts_dir = os.path.join(ext_dir, "scripts")
                if scripts_dir not in sys.path:
                    sys.path.insert(0, scripts_dir)
                from queue_interceptor import queue_state, get_queue_state, get_intercept_timeout
                import time

                state = get_queue_state()
                with state['lock']:
                    is_active = state['intercept_next']
                    tab = state['intercept_tab']
                    timestamp = state['intercept_timestamp']
                    last_result = state['last_result']

                    # Calculate remaining time if active
                    remaining = None
                    timed_out = False
                    if is_active and timestamp is not None:
                        timeout = get_intercept_timeout()
                        elapsed = time.time() - timestamp
                        remaining = max(0, timeout - elapsed)
                        if elapsed > timeout:
                            timed_out = True
                            # Auto-clear timed out state
                            state['intercept_next'] = False
                            state['intercept_tab'] = None
                            state['intercept_timestamp'] = None
                            is_active = False

                return JSONResponse({
                    "success": True,
                    "is_active": is_active,
                    "tab": tab,
                    "remaining_seconds": remaining,
                    "timed_out": timed_out,
                    "last_result": last_result
                })

            except Exception as e:
                return JSONResponse({
                    "success": False,
                    "error": f"Failed to get intercept state: {str(e)}"
                }, status_code=500)

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    # =========================================================================
    # Bookmark Endpoints
    # =========================================================================

    @app.get("/task-scheduler/bookmarks")
    async def get_bookmarks():
        """Get all bookmarks."""
        try:
            from .db import get_database
            import json

            db = get_database()
            bookmarks = db.get_all_bookmarks()

            # Parse JSON fields for display
            def process_bookmark(b):
                result = dict(b)
                # Parse params if it's a string
                if isinstance(result.get('params'), str):
                    try:
                        result['params'] = json.loads(result['params'])
                    except:
                        pass
                return result

            return JSONResponse({
                "success": True,
                "bookmarks": [process_bookmark(b) for b in bookmarks],
                "count": len(bookmarks)
            })

        except Exception as e:
            traceback.print_exc()
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.get("/task-scheduler/bookmarks/{bookmark_id}")
    async def get_bookmark(bookmark_id: str):
        """Get a specific bookmark by ID."""
        try:
            from .db import get_database
            import json

            db = get_database()
            bookmark = db.get_bookmark(bookmark_id)

            if not bookmark:
                raise HTTPException(status_code=404, detail="Bookmark not found")

            # Parse JSON fields
            if isinstance(bookmark.get('params'), str):
                try:
                    bookmark['params'] = json.loads(bookmark['params'])
                except:
                    pass
            if isinstance(bookmark.get('script_args'), str):
                try:
                    bookmark['script_args'] = json.loads(bookmark['script_args'])
                except:
                    pass

            return JSONResponse({
                "success": True,
                "bookmark": bookmark
            })

        except HTTPException:
            raise
        except Exception as e:
            traceback.print_exc()
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/bookmarks")
    async def create_bookmark(name: str = "Untitled"):
        """Create a bookmark from the current intercept data."""
        try:
            from .db import get_database
            import json

            # Get the last intercept result
            _, get_result, clear_mode = get_intercept_functions()
            if get_result is None:
                return JSONResponse({
                    "success": False,
                    "error": "Intercept module not available"
                }, status_code=500)

            result = get_result()
            if not result or result.get('status') != 'queued':
                return JSONResponse({
                    "success": False,
                    "error": "No valid intercept data available. Use the Queue button first."
                }, status_code=400)

            # Extract data from the intercept result
            task_data = result.get('task', {})

            db = get_database()
            bookmark_data = {
                'name': name,
                'task_type': task_data.get('task_type', 'txt2img'),
                'params': json.dumps(task_data.get('params', {})),
                'checkpoint': task_data.get('checkpoint', ''),
                'script_args': json.dumps(task_data.get('script_args', []))
            }

            bookmark = db.add_bookmark(bookmark_data)

            return JSONResponse({
                "success": True,
                "bookmark_id": bookmark['id'],
                "message": f"Bookmark '{name}' created"
            })

        except Exception as e:
            traceback.print_exc()
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.post("/task-scheduler/bookmarks/from-task/{task_id}")
    async def create_bookmark_from_task(task_id: str, name: str = ""):
        """Create a bookmark from an existing task."""
        try:
            from .db import get_database
            import json

            queue_manager = get_queue_manager()
            task = queue_manager.get_task(task_id)

            if not task:
                raise HTTPException(status_code=404, detail="Task not found")

            db = get_database()
            bookmark_name = name if name else f"Bookmark from {task.get_display_name()[:30]}"

            bookmark_data = {
                'name': bookmark_name,
                'task_type': task.task_type.value,
                'params': json.dumps(task.params),
                'checkpoint': task.checkpoint or '',
                'script_args': json.dumps(task.script_args)
            }

            bookmark = db.add_bookmark(bookmark_data)

            return JSONResponse({
                "success": True,
                "bookmark_id": bookmark['id'],
                "message": f"Bookmark '{bookmark_name}' created"
            })

        except HTTPException:
            raise
        except Exception as e:
            traceback.print_exc()
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.put("/task-scheduler/bookmarks/{bookmark_id}")
    async def update_bookmark(bookmark_id: str, name: str = None):
        """Update a bookmark's name."""
        try:
            from .db import get_database

            db = get_database()
            bookmark = db.get_bookmark(bookmark_id)

            if not bookmark:
                raise HTTPException(status_code=404, detail="Bookmark not found")

            updates = {}
            if name is not None:
                updates['name'] = name

            if updates:
                db.update_bookmark(bookmark_id, updates)

            return JSONResponse({
                "success": True,
                "message": "Bookmark updated"
            })

        except HTTPException:
            raise
        except Exception as e:
            traceback.print_exc()
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.delete("/task-scheduler/bookmarks/{bookmark_id}")
    async def delete_bookmark(bookmark_id: str):
        """Delete a bookmark."""
        try:
            from .db import get_database

            db = get_database()
            success = db.delete_bookmark(bookmark_id)

            if not success:
                raise HTTPException(status_code=404, detail="Bookmark not found")

            return JSONResponse({
                "success": True,
                "message": "Bookmark deleted"
            })

        except HTTPException:
            raise
        except Exception as e:
            traceback.print_exc()
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    @app.get("/task-scheduler/bookmarks/count")
    async def get_bookmark_count():
        """Get the number of bookmarks."""
        try:
            from .db import get_database

            db = get_database()
            count = db.get_bookmark_count()

            return JSONResponse({
                "success": True,
                "count": count
            })

        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e)
            }, status_code=500)

    print("[TaskScheduler] API endpoints registered")
