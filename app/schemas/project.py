from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict


class ProjectConfig(BaseModel):
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
    zip_object_key: str | None = Field(default=None, max_length=512)
    config_json: ProjectConfig | dict | None = None

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, value):
        if value and not (value.startswith("https://") or value.startswith("http://") or value.startswith("git@")):
            raise ValueError("repo_url必须是http(s)或git地址")
        return value


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    language: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    config_json: ProjectConfig | dict | None = None


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
    config_json: ProjectConfig | dict
