from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.responses import request_trace_id, success
from app.models.user import User
from app.schemas.diagram import AnalysisCreate, AnalysisStartOut, DiagramOut
from app.schemas.task import TaskOut
from app.services.diagram_service import DiagramService
from app.services.project_service import ProjectService
from app.services.task_service import TaskService

router = APIRouter(tags=["analysis"])


@router.post("/projects/{project_id}/analysis")
def create_analysis(project_id: int, payload: AnalysisCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project_service = ProjectService(db)
    project = project_service.get_owned(current_user, project_id)
    task = project_service.create_task(current_user, project, "diagram", "图表分析任务已创建")
    db.flush()
    diagram = DiagramService(db).create_analysis(current_user, project, task, payload)
    data = AnalysisStartOut(task_id=task.id, status=task.status, diagram_id=diagram.id).model_dump()
    return success(data, trace_id=request_trace_id(request))


@router.get("/analysis/{task_id}")
def get_analysis(task_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = TaskService(db).get_task(current_user, task_id)
    return success(TaskOut.model_validate(task).model_dump(), trace_id=request_trace_id(request))
