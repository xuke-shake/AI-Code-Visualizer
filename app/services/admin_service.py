from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.agent_run import AgentRun
from app.models.analysis_task import AnalysisTask
from app.models.audit_log import AuditLog
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.quota import Quota
from app.models.user import User
from app.schemas.admin import QuotaUpdate


class AdminService:
    def __init__(self, db: Session):
        self.db = db

    def metrics(self) -> dict:
        user_count = int(self.db.scalar(select(func.count()).select_from(User)) or 0)
        project_count = int(self.db.scalar(select(func.count()).select_from(Project)) or 0)
        task_count = int(self.db.scalar(select(func.count()).select_from(AnalysisTask)) or 0)
        failed_task_count = int(self.db.scalar(select(func.count()).select_from(AnalysisTask).where(AnalysisTask.status == "failed")) or 0)
        diagram_count = int(self.db.scalar(select(func.count()).select_from(Diagram)) or 0)
        token_usage = int(self.db.scalar(select(func.coalesce(func.sum(AgentRun.prompt_tokens + AgentRun.completion_tokens), 0))) or 0)
        success_rate = 1.0 if task_count == 0 else round((task_count - failed_task_count) / task_count, 4)
        return {
            "user_count": user_count,
            "project_count": project_count,
            "task_count": task_count,
            "failed_task_count": failed_task_count,
            "success_rate": success_rate,
            "diagram_count": diagram_count,
            "token_usage": token_usage,
        }

    def update_quota(self, user_id: int, payload: QuotaUpdate) -> Quota:
        quota = self.db.scalar(select(Quota).where(Quota.user_id == user_id))
        if not quota:
            quota = Quota(user_id=user_id)
            self.db.add(quota)
            self.db.flush()
        for key, value in payload.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(quota, key, value)
        self.db.commit()
        self.db.refresh(quota)
        return quota
