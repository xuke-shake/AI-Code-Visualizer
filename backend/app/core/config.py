from functools import lru_cache
from pathlib import Path
from typing import Annotated
import json

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Code Visualizer Backend"
    app_env: str = "dev"
    debug: bool = True

    database_url: str = "sqlite:///./dev.db"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    storage_dir: str = "./storage"
    max_upload_size_mb: int = Field(default=50, ge=1)
    max_zip_files: int = Field(default=2000, ge=1)
    max_zip_member_uncompressed_size_mb: int = Field(default=10, ge=1)
    max_zip_total_uncompressed_size_mb: int = Field(default=100, ge=1)
    max_zip_compression_ratio: float = Field(default=100.0, gt=1)
    git_command_timeout_seconds: int = Field(default=120, ge=1, le=3600)
    git_low_speed_seconds: int = Field(default=30, ge=1, le=600)
    git_max_snapshot_files: int = Field(default=10000, ge=1)
    git_max_snapshot_size_mb: int = Field(default=500, ge=1)
    git_max_snapshot_file_size_mb: int = Field(default=50, ge=1)

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # LLM 配置统一由 Settings 读取；支持 auto/rule/model/off，兼容旧的
    # true/false/on/off 环境变量写法。
    llm_enabled: str = "auto"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    llm_max_context_chars: int = Field(default=12000, ge=1000, le=200000)
    llm_max_output_tokens: int = Field(default=4000, ge=128, le=32000)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                return [item.strip() for item in raw.split(",") if item.strip()]
            if isinstance(decoded, list):
                return [str(item).strip() for item in decoded if str(item).strip()]
            return [raw]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return value

    @field_validator("llm_enabled", mode="before")
    @classmethod
    def normalise_llm_enabled(cls, value):
        if isinstance(value, bool):
            return "model" if value else "off"
        normalized = str(value or "auto").strip().lower()
        aliases = {
            "1": "model",
            "true": "model",
            "yes": "model",
            "on": "model",
            "0": "off",
            "false": "off",
            "no": "off",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"auto", "rule", "model", "off"}:
            raise ValueError("LLM_ENABLED必须是auto、rule、model或off")
        return normalized

    @model_validator(mode="after")
    def validate_runtime_security(self):
        environment = self.app_env.strip().lower()
        if environment not in {"dev", "development", "test", "testing"}:
            placeholder_keys = {
                "",
                "change-me-in-production",
                "change-me",
                "secret",
                "test-secret",
            }
            if self.secret_key.strip().lower() in placeholder_keys or len(self.secret_key) < 32:
                raise ValueError("非开发环境必须配置至少32字符的非占位SECRET_KEY")
            # 非开发环境始终关闭 debug，避免向客户端暴露内部异常详情。
            self.debug = False
        return self

    @property
    def llm_model_enabled(self) -> bool:
        if self.llm_enabled == "off" or self.llm_enabled == "rule":
            return False
        if self.llm_enabled == "model":
            return bool(self.llm_api_key)
        return bool(self.llm_api_key)

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
