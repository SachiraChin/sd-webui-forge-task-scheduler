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
            queue_manager = get_queue_manager()
            tasks = queue_manager.get_all_tasks()

            return JSONResponse({
                "success": True,
                "tasks": [
                    {
                        "id": t.id,
                        "task_type": t.task_type.value,
                        "status": t.status.value,
                        "name": t.get_display_name(),
                        "checkpoint": t.get_short_checkpoint(),
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "priority": t.priority
                    }
                    for t in tasks
                ]
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
        """Get queue status."""
        try:
            executor = get_executor()
            status = executor.get_status()

            return JSONResponse({
                "success": True,
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

    print("[TaskScheduler] API endpoints registered")
