import logging
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.responses import request_trace_id, success
from app.models.user import User
from app.schemas.common import Page
from app.schemas.project import ProjectConfigUpdate, ProjectCreate, ProjectCreateOut, ProjectOrderBy, ProjectOut, ProjectUpdate
from app.schemas.task import ParseRequest, SyncRequest, TaskStartOut
from app.services.audit_service import AuditService
from app.services.index_service import IndexService
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.services.git_service import GitImportError, GitService
from app.services.diagram_service import DiagramService
from app.core.config import get_settings
from app.models.source_file import SourceFile
from app.models.diagram import Diagram
from app.schemas.diagram import DiagramOut

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


@router.get("")
def list_projects(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: str | None = None,
    language: str | None = None,
    order_by: ProjectOrderBy = Query(ProjectOrderBy.updated_at),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items, total = ProjectService(db).list_projects(current_user, page, page_size, keyword, language, order_by, order)
    data = Page[ProjectOut](
        items=[ProjectOut.model_validate(item) for item in items], total=total, page=page, page_size=page_size
    ).model_dump()
    return success(data, trace_id=request_trace_id(request))


@router.post("")
def create_project(payload: ProjectCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = ProjectService(db).create_project(current_user, payload)
    cloned_path = None
    
    # Git 导入由受限服务统一处理；失败时保留项目 failed 状态供后续查询。
    if payload.source_type == "git" and payload.repo_url:
        try:
            clone_path = GitService().clone_for_project(payload.repo_url, payload.branch, project.id)
            cloned_path = clone_path
            if project.repository is not None:
                # Store a controlled, storage-relative path rather than an
                # arbitrary client path or machine-specific absolute path.
                storage_root = get_settings().storage_path.resolve()
                project.repository.local_path = clone_path.resolve().relative_to(storage_root).as_posix()
                db.flush()
        except GitImportError:
            project.status = "failed"
            db.commit()
            raise HTTPException(status_code=400, detail="Git仓库导入失败，请确认是允许的公开GitHub仓库")

    try:
        AuditService(db).record(current_user.id, "project.create", "project", project.id, {"name": project.name}, request)
        db.commit()
    except Exception:
        db.rollback()
        if cloned_path is not None:
            GitService().remove_project_path(project.id)
        raise
    data = ProjectCreateOut(project=ProjectOut.model_validate(project), task_id=None).model_dump()
    return success(data, trace_id=request_trace_id(request))


@router.get("/{project_id}")
def get_project(project_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = ProjectService(db).get_owned(current_user, project_id)
    return success(ProjectOut.model_validate(project).model_dump(), trace_id=request_trace_id(request))


@router.patch("/{project_id}")
def update_project(project_id: int, payload: ProjectUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = ProjectService(db).update_project(current_user, project_id, payload)
    AuditService(db).record(current_user.id, "project.update", "project", project.id, payload.model_dump(exclude_unset=True), request)
    db.commit()
    return success(ProjectOut.model_validate(project).model_dump(), trace_id=request_trace_id(request))


@router.delete("/{project_id}")
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Record the audit row before the service commits destructive cleanup so
    # the project operation and audit event share one request transaction.
    AuditService(db).record(current_user.id, "project.delete", "project", project_id, request=request)
    ProjectService(db).delete_project(current_user, project_id)
    return success({"deleted": True}, trace_id=request_trace_id(request))


@router.get("/{project_id}/config")
def get_config(project_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = ProjectService(db).get_owned(current_user, project_id)
    return success(project.config_json or {}, trace_id=request_trace_id(request))


@router.patch("/{project_id}/config")
def update_config(project_id: int, payload: ProjectConfigUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    config = payload.config_json.model_dump() if hasattr(payload.config_json, "model_dump") else dict(payload.config_json)
    project = ProjectService(db).update_project(current_user, project_id, ProjectUpdate(config_json=config))
    db.commit()
    return success(project.config_json or {}, trace_id=request_trace_id(request))


@router.post("/{project_id}/parse")
def parse_project(
    project_id: int,
    payload: ParseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.mode == "async":
        raise HTTPException(status_code=400, detail="当前解析接口仅支持同步模式")
    service = ProjectService(db)
    project = service.get_owned(current_user, project_id)

    task = service.create_task(current_user, project, "parse", "解析任务已创建")

    db.flush()
    db.commit()
    db.refresh(task)

    try:
        task = IndexService(db).parse_full(project, task)
    except Exception as exc:
        trace_id = request_trace_id(request)
        logger.exception("解析任务异常 trace_id=%s project_id=%s task_id=%s", trace_id, project_id, task.id, exc_info=exc)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="解析任务执行失败",
        )

    if task is None:
        raise HTTPException(
            status_code=500,
            detail="解析任务执行失败",
        )

    data = TaskStartOut(
        task_id=task.id,
        status=task.status,
        progress=task.progress,
    ).model_dump()

    return success(data, trace_id=request_trace_id(request))


@router.post("/{project_id}/sync")
def sync_project(project_id: int, payload: SyncRequest, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ProjectService(db)
    project = service.get_owned(current_user, project_id)
    task = service.create_task(current_user, project, "sync", "同步任务已创建")
    db.flush()
    task = IndexService(db).sync_incremental(project, task)
    data = TaskStartOut(task_id=task.id, status=task.status, progress=task.progress).model_dump()
    return success(data, trace_id=request_trace_id(request))


@router.get("/{project_id}/changes")
def project_changes(project_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ProjectService(db).get_owned(current_user, project_id)
    task = TaskService(db).latest_task_for_project(current_user, project_id, task_type="sync")
    if task is None:
        data = {
            "task_id": None,
            "status": None,
            "added": [],
            "modified": [],
            "deleted": [],
            "unchanged": 0,
            "outdated_diagrams": 0,
        }
    else:
        result = task.result_json if isinstance(task.result_json, dict) else {}
        data = {
            "task_id": task.id,
            "status": task.status,
            "added": result.get("added", []),
            "modified": result.get("modified", []),
            "deleted": result.get("deleted", []),
            "unchanged": result.get("unchanged", 0),
            "outdated_diagrams": result.get("outdated_diagrams", 0),
        }
    return success(data, trace_id=request_trace_id(request))


def build_file_tree(source_files: list[SourceFile]) -> list[dict]:
    root: list[dict] = []
    dir_index: dict[str, dict] = {}

    for sf in source_files:
        parts = [p for p in sf.relative_path.replace("\\", "/").split("/") if p]
        if not parts:
            continue

        current_children = root
        current_path = ""

        for part in parts[:-1]:
            current_path = f"{current_path}/{part}" if current_path else part

            node = dir_index.get(current_path)
            if node is None:
                node = {
                    "id": f"dir:{current_path}",
                    "name": part,
                    "path": current_path,
                    "type": "directory",
                    "children": [],
                }
                dir_index[current_path] = node
                current_children.append(node)

            current_children = node["children"]

        file_path = "/".join(parts)
        current_children.append(
            {
                "id": f"file:{sf.id}",
                "name": parts[-1],
                "path": file_path,
                "type": "file",
            }
        )

    return root


@router.get("/{project_id}/tree")
def get_project_tree(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ProjectService(db).get_owned(current_user, project_id)

    files = (
        db.query(SourceFile)
        .filter(SourceFile.project_id == project_id)
        .order_by(SourceFile.relative_path.asc())
        .all()
    )

    return success(build_file_tree(files), trace_id=request_trace_id(request))


@router.get("/{project_id}/diagram")
def get_latest_project_diagram(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ProjectService(db).get_owned(current_user, project_id)

    diagram = (
        db.query(Diagram)
        .filter(Diagram.project_id == project_id)
        .order_by(Diagram.created_at.desc())
        .first()
    )

    if not diagram:
        return success(None, trace_id=request_trace_id(request))

    data = DiagramService(db).serialize_diagram(diagram)
    return success(DiagramOut.model_validate(data).model_dump(), trace_id=request_trace_id(request))
