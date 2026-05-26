from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.user import UserOut, QuotaOut
from app.schemas.task import TaskOut


class MetricsOut(BaseModel):
    user_count: int
    project_count: int
    task_count: int
    failed_task_count: int
    success_rate: float
    diagram_count: int
    token_usage: int


class QuotaUpdate(BaseModel):
    max_projects: int | None = Field(default=None, ge=1, le=10000)
    max_files_per_project: int | None = Field(default=None, ge=1, le=100000)
    max_concurrent_tasks: int | None = Field(default=None, ge=1, le=100)
    monthly_token_limit: int | None = Field(default=None, ge=0)
    used_tokens_this_month: int | None = Field(default=None, ge=0)


class UserWithQuota(BaseModel):
    user: UserOut
    quota: QuotaOut | None = None


class AuditLogOut(BaseModel):
    id: int
    user_id: int | None = None
    action: str
    target_type: str | None = None
    target_id: int | None = None
    ip_address: str | None = None
    detail_json: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
