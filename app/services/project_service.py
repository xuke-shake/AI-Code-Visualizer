from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.analysis_task import AnalysisTask
from app.models.project import Project
from app.models.repository import Repository
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate

DEFAULT_CONFIG = {
    "chunking_strategy": "function",
    "retrieval_top_k": 8,
    "similarity_threshold": 0.35,
    "enable_symbol_search": True,
    "model_name": None,
    "max_tokens": 4000,
}


class ProjectService:
    def __init__(self, db: Session):
        self.db = db

    def get_owned(self, user: User, project_id: int) -> Project:
        project = self.db.get(Project, project_id)
        if not project:
            raise NotFoundException("项目不存在")
        if user.role != "admin" and project.owner_id != user.id:
            raise ForbiddenException("无权访问该项目")
        return project

    def list_projects(
        self,
        user: User,
        page: int = 1,
        page_size: int = 10,
        keyword: str | None = None,
        language: str | None = None,
        order_by: str = "updated_at",
        order: str = "desc",
    ) -> tuple[list[Project], int]:
        stmt = select(Project).where(Project.owner_id == user.id)
        count_stmt = select(func.count()).select_from(Project).where(Project.owner_id == user.id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(Project.name.ilike(like))
            count_stmt = count_stmt.where(Project.name.ilike(like))
        if language:
            stmt = stmt.where(Project.language == language)
            count_stmt = count_stmt.where(Project.language == language)
        order_col = getattr(Project, order_by, Project.updated_at)
        stmt = stmt.order_by(order_col.asc() if order == "asc" else order_col.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        return list(self.db.scalars(stmt).all()), int(self.db.scalar(count_stmt) or 0)

    def create_project(self, user: User, payload: ProjectCreate) -> Project:
        config: dict[str, Any]
        if payload.config_json is None:
            config = DEFAULT_CONFIG.copy()
        elif hasattr(payload.config_json, "model_dump"):
            config = payload.config_json.model_dump()
        else:
            config = dict(payload.config_json)
        project = Project(
            owner_id=user.id,
            name=payload.name,
            language=payload.language,
            source_type=payload.source_type,
            status="created",
            config_json={**DEFAULT_CONFIG, **config},
        )
        self.db.add(project)
        self.db.flush()
        repo = Repository(
            project_id=project.id,
            repo_url=payload.repo_url,
            branch=payload.branch,
            zip_object_key=payload.zip_object_key,
        )
        self.db.add(repo)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update_project(self, user: User, project_id: int, payload: ProjectUpdate) -> Project:
        project = self.get_owned(user, project_id)
        data = payload.model_dump(exclude_unset=True)
        if "config_json" in data and data["config_json"] is not None and hasattr(data["config_json"], "model_dump"):
            data["config_json"] = data["config_json"].model_dump()
        for key, value in data.items():
            if value is not None:
                setattr(project, key, value)
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete_project(self, user: User, project_id: int) -> None:
        project = self.get_owned(user, project_id)
        self.db.delete(project)
        self.db.commit()

    def create_task(self, user: User, project: Project, task_type: str, message: str | None = None) -> AnalysisTask:
        task = AnalysisTask(
            project_id=project.id,
            user_id=user.id,
            task_type=task_type,
            status="pending",
            progress=0,
            message=message,
        )
        self.db.add(task)
        self.db.flush()
        return task
