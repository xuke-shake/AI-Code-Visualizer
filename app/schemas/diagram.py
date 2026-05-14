from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class AnalysisCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    diagram_type: str = Field(default="flowchart", pattern="^(flowchart|sequence|state|architecture)$")
    scope: str | None = Field(default=None, max_length=512)
    title: str | None = Field(default=None, max_length=128)
    parameters: dict | None = None


class AnalysisStartOut(BaseModel):
    task_id: int
    status: str
    diagram_id: int | None = None


class DiagramOut(BaseModel):
    id: int
    project_id: int
    creator_id: int
    title: str
    diagram_type: str
    prompt: str | None = None
    mermaid_code: str
    node_mapping_json: dict | None = None
    version: int
    is_outdated: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiagramUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    mermaid_code: str | None = Field(default=None, min_length=1)
    node_mapping_json: dict | None = None


class ExportRequest(BaseModel):
    format: str = Field(pattern="^(markdown|svg|png|pdf)$")
    filename: str | None = Field(default=None, max_length=128)


class ExportOut(BaseModel):
    download_url: str
    object_key: str
    format: str


class ShareRequest(BaseModel):
    expire_hours: int = Field(default=72, ge=1, le=24 * 30)


class ShareOut(BaseModel):
    share_url: str
    share_token: str
    expires_at: datetime
