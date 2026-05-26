import asyncio
import json
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.responses import request_trace_id, success
from app.models.user import User
from app.schemas.task import TaskOut
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}")
def get_task(task_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = TaskService(db).get_task(current_user, task_id)
    return success(TaskOut.model_validate(task).model_dump(), trace_id=request_trace_id(request))


@router.get("/{task_id}/events")
def task_events(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = TaskService(db).get_task(current_user, task_id)

    async def event_stream():
        payload = {
            "task_id": task.id,
            "status": task.status,
            "progress": task.progress,
            "stage": task.task_type,
            "message": task.message,
        }
        yield "event: task_progress\n"
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.01)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
