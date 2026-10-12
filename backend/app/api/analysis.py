import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.responses import fail, request_trace_id, success
from app.models.analysis_task import AnalysisTask
from app.models.user import User
from app.schemas.diagram import AnalysisCreate, AnalysisStartOut, DiagramOut
from app.schemas.task import TaskOut
from app.services.diagram_service import DiagramService
from app.services.index_service import has_current_index
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.core.exceptions import AppException, ConflictException
from app.models.source_file import SourceFile
from sqlalchemy import select


logger = logging.getLogger(__name__)


def _persist_failed_analysis(db: Session, task_id: int, message: str) -> None:
    try:
        db.rollback()
        task = db.get(AnalysisTask, task_id)
        if task is None:
            return
        task.status = "failed"
        task.progress = 100
        task.message = message
        task.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("failed to persist diagram task failure task_id=%s", task_id)

router = APIRouter(tags=["analysis"])


@router.post("/projects/{project_id}/analysis")

def create_analysis(project_id: int, payload: AnalysisCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project_service = ProjectService(db)
    project = project_service.get_owned(current_user, project_id)
    if not has_current_index(project):
        raise ConflictException("当前源码尚未完成解析，请先解析后生成")

    if payload.parameters and "selectedPaths" in payload.parameters:
        selected_paths = payload.parameters.get("selectedPaths")
        if selected_paths is not None:
            if not selected_paths:
                raise AppException("请至少选择一个已解析文件")
            known_paths = set(db.scalars(select(SourceFile.relative_path).where(SourceFile.project_id == project_id)).all())
            if set(selected_paths) - known_paths:
                raise AppException("所选文件不属于项目已解析文件")

    preflight_source = (project.last_index_version, project.repository.upload_id if project.repository else None)
    task = project_service.create_task(current_user, project, "diagram", "图表分析任务已创建")
    task.status = "running"
    task.progress = 10
    task.message = "正在准备图表生成"
    task_id = task.id
    db.commit()

    try:
        diagram = DiagramService(db).create_analysis(
            current_user.id, project_id, task_id, payload, expected_source=preflight_source,
        )
    except AppException as exc:
        _persist_failed_analysis(db, task_id, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(
                exc.code,
                exc.message,
                trace_id=request_trace_id(request),
                data={"task_id": task_id, "status": "failed"},
            ),
        )
    except Exception:
        logger.exception(
            "diagram generation failed task_id=%s trace_id=%s",
            task_id,
            request_trace_id(request),
        )
        message = "图表生成失败，请凭任务编号重试或排查"
        _persist_failed_analysis(db, task_id, message)
        return JSONResponse(
            status_code=500,
            content=fail(
                50000,
                message,
                trace_id=request_trace_id(request),
                data={"task_id": task_id, "status": "failed"},
            ),
        )

    task = db.get(AnalysisTask, task_id)
    metadata = task.result_json if task and isinstance(task.result_json, dict) else {}
    data = AnalysisStartOut(
        task_id=task_id,
        status=task.status if task else "success",
        diagram_id=diagram.id,
        generation_mode=metadata.get("generation_mode"),
        quality_status=metadata.get("quality_status"),
        reason=metadata.get("reason"),
    ).model_dump()
    return success(data, trace_id=request_trace_id(request))


@router.get("/analysis/{task_id}")
def get_analysis(task_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = TaskService(db).get_task(current_user, task_id)
    return success(TaskOut.model_validate(task).model_dump(), trace_id=request_trace_id(request))
