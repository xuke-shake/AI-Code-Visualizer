from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.services.git_service import validate_github_repo_url


class ProjectOrderBy(str, Enum):
    name = "name"
    language = "language"
    status = "status"
    file_count = "file_count"
    created_at = "created_at"
    updated_at = "updated_at"


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chunking_strategy: str = "function"
    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    similarity_threshold: float = Field(default=0.35, ge=0, le=1)
    enable_symbol_search: bool = True
    model_name: str | None = None
    max_tokens: int = Field(default=4000, ge=512, le=32000)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    language: str | None = Field(default=None, max_length=64)
    source_type: str = Field(pattern="^(git|zip)$")
    repo_url: str | None = Field(default=None, max_length=512)
    branch: str | None = Field(default=None, max_length=128)
    upload_id: int | None = Field(default=None, ge=1)
    config_json: ProjectConfig | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_source(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("项目名称不能为空")
        if self.source_type == "zip" and self.upload_id is None:
            raise ValueError("ZIP项目必须提供upload_id")
        if self.source_type == "git" and self.upload_id is not None:
            raise ValueError("Git项目不能提供upload_id")
        if self.source_type == "git" and self.repo_url is None:
            raise ValueError("Git项目必须提供repo_url")
        if self.source_type == "zip" and self.repo_url is not None:
            raise ValueError("ZIP项目不能提供repo_url")
        return self

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value):
        if value:
            value = value.strip()
            try:
                validate_github_repo_url(value)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
        return value or None

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, value):
        if value is not None and (not value.strip() or value.startswith("-") or any(ord(ch) < 32 for ch in value)):
            raise ValueError("branch包含非法字符")
        return value


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    language: str | None = Field(default=None, max_length=64)
    config_json: ProjectConfig | None = None
    upload_id: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip() if value is not None else value
        if value == "":
            raise ValueError("项目名称不能为空")
        return value


class ProjectOut(BaseModel):
    id: int
    owner_id: int
    name: str
    language: str | None = None
    source_type: str
    status: str
    file_count: int
    last_index_version: str | None = None
    config_json: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectCreateOut(BaseModel):
    project: ProjectOut
    task_id: int | None = None


class ProjectConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config_json: ProjectConfig
