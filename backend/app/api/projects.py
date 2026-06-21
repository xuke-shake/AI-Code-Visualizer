import os
import shutil
import subprocess
import traceback
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.config import get_settings
from app.core.responses import request_trace_id, success
from app.models.user import User
from app.schemas.common import Page
from app.schemas.project import ProjectConfigUpdate, ProjectCreate, ProjectCreateOut, ProjectOut, ProjectUpdate
from app.schemas.task import ParseRequest, SyncRequest, TaskStartOut
from app.services.audit_service import AuditService
from app.services.index_service import IndexService
from app.services.project_service import ProjectService
from app.models.source_file import SourceFile
from app.models.diagram import Diagram
from app.schemas.diagram import DiagramOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def list_projects(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: str | None = None,
    language: str | None = None,
    order_by: str = "updated_at",
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
    
    # === 🚀 核心新增：监听 Git 仓库并自动高速下载 ===
    if payload.source_type == "git" and payload.repo_url:
        settings = get_settings()
        
        # 💡 【关键注意】：这里假设存放解析代码的真实文件夹是 storage_path / projects / 项目ID。
        # 如果你们后端存 ZIP 解压文件的真实路径不长这样（比如叫 repos），请务必在这行修改！
        project_dir = os.path.join(settings.storage_path, "projects", str(project.id))
        
        try:
            # 1. 确保将要克隆的目录干干净净
            if os.path.exists(project_dir):
                shutil.rmtree(project_dir)
            os.makedirs(project_dir, exist_ok=True)
            
            # 2. 组装克隆大炮 (--depth 1 代表只拉最新代码，丢弃历史记录，速度起飞)
            clone_cmd = ["git", "clone", "--depth", "1"]
            if payload.branch:
                clone_cmd.extend(["-b", payload.branch])
            clone_cmd.extend([payload.repo_url, project_dir])
            
            # 3. 防止拉取私密仓库时，终端一直弹窗要输入密码，导致后端死锁卡挂
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
            
            # 4. 开火！呼叫操作系统执行
            subprocess.run(clone_cmd, check=True, capture_output=True, text=True, env=env)
            
        except subprocess.CalledProcessError as e:
            # 发现错误（比如网址不存在），立刻回滚删掉刚才数据库里建好的项目，并向网页发精准报错
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Git 仓库拉取失败，请确保是公开仓库且地址正确！详细: {e.stderr.strip()}")
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"服务器执行 Git 命令时发生内部错误: {str(e)}")
    # =========================================================

    AuditService(db).record(current_user.id, "project.create", "project", project.id, {"name": project.name}, request)
    db.commit()
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
    ProjectService(db).delete_project(current_user, project_id)
    AuditService(db).record(current_user.id, "project.delete", "project", project_id, request=request)
    db.commit()
    return success({"deleted": True}, trace_id=request_trace_id(request))


@router.get("/{project_id}/config")
def get_config(project_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = ProjectService(db).get_owned(current_user, project_id)
    return success(project.config_json or {}, trace_id=request_trace_id(request))


@router.patch("/{project_id}/config")
def update_config(project_id: int, payload: ProjectConfigUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    config = payload.config_json.model_dump() if hasattr(payload.config_json, "model_dump") else dict(payload.config_json)
    project = ProjectService(db).update_project(current_user, project_id, ProjectUpdate(config_json=config))
    return success(project.config_json or {}, trace_id=request_trace_id(request))


@router.post("/{project_id}/parse")
def parse_project(
    project_id: int,
    payload: ParseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProjectService(db)
    project = service.get_owned(current_user, project_id)

    task = service.create_task(current_user, project, "parse", "解析任务已创建")

    db.flush()
    db.commit()
    db.refresh(task)

    print("DEBUG parse before:", task.id, task.status, task.progress)

    try:
        task = IndexService(db).parse_full(project, task)
    except Exception as exc:
        traceback.print_exc()
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"parse_full 抛出异常: {type(exc).__name__}: {exc}",
        )

    print("DEBUG parse after:", task)

    if task is None:
        raise HTTPException(
            status_code=500,
            detail="parse_full 返回了 None，请检查 index_service.py 里 parse_full 是否所有分支都有 return task",
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
    return success({"added": [], "modified": [], "deleted": []}, trace_id=request_trace_id(request))


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

    return success(
        DiagramOut.model_validate(diagram).model_dump(),
        trace_id=request_trace_id(request),
    )