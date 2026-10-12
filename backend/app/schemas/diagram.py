from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnalysisCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    diagram_type: str = Field(default="flowchart", pattern="^(flowchart|sequence|state|architecture)$")
    scope: str | None = Field(default=None, max_length=8000)
    title: str | None = Field(default=None, max_length=128)
    parameters: dict | None = None

    @field_validator("prompt", mode="before")
    @classmethod
    def normalize_prompt(cls, value):
        if not isinstance(value, str):
            raise ValueError("prompt必须是字符串")
        value = value.strip()
        if not value:
            raise ValueError("指令不能为空")
        return value

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value):
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("parameters必须是对象")
        if "selectedPaths" in value:
            paths = value["selectedPaths"]
            if paths is not None and (not isinstance(paths, list) or not all(isinstance(item, str) for item in paths)):
                raise ValueError("selectedPaths必须是字符串列表")
        return value


class AnalysisStartOut(BaseModel):
    task_id: int
    status: str
    diagram_id: int | None = None
    generation_mode: str | None = None
    quality_status: str | None = None
    reason: str | None = None


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
    generation_mode: str | None = None
    quality_status: str | None = None
    generation_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DiagramUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=128)
    mermaid_code: str | None = Field(default=None, min_length=1)


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
