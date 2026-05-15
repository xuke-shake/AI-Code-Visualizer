from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.analysis_task import AnalysisTask
from app.models.project import Project
from app.models.user import User


class TaskService:
    def __init__(self, db: Session):
        self.db = db

    def get_task(self, user: User, task_id: int) -> AnalysisTask:
        task = self.db.get(AnalysisTask, task_id)
        if not task:
            raise NotFoundException("任务不存在")
        project = self.db.get(Project, task.project_id)
        if not project or (user.role != "admin" and project.owner_id != user.id):
            raise ForbiddenException("无权访问该任务")
        return task

    def finish_success(self, task: AnalysisTask, result: dict | None = None, message: str = "success") -> AnalysisTask:
        task.status = "success"
        task.progress = 100
        task.message = message
        task.result_json = result or {}
        task.finished_at = datetime.now(timezone.utc)
        self.db.flush()
        return task

    def fail(self, task: AnalysisTask, message: str) -> AnalysisTask:
        task.status = "failed"
        task.message = message
        task.finished_at = datetime.now(timezone.utc)
        self.db.flush()
        return task

    def latest_task_for_project(self, user: User, project_id: int, task_type: str | None = None) -> AnalysisTask | None:
        stmt = select(AnalysisTask).where(AnalysisTask.project_id == project_id).order_by(AnalysisTask.created_at.desc())
        if task_type:
            stmt = stmt.where(AnalysisTask.task_type == task_type)
        task = self.db.scalar(stmt.limit(1))
        if task:
            self.get_task(user, task.id)
        return task
