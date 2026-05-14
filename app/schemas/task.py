from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class TaskOut(BaseModel):
    id: int
    project_id: int
    user_id: int
    task_type: str
    status: str
    progress: int
    message: str | None = None
    result_json: dict | None = None
    created_at: datetime
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ParseRequest(BaseModel):
    mode: str = Field(default="auto", pattern="^(auto|sync|async)$")


class SyncRequest(BaseModel):
    branch: str | None = None
    version: str | None = None


class TaskStartOut(BaseModel):
    task_id: int
    status: str
    progress: int = 0
