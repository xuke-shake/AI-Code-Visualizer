from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    id: int
    email: EmailStr
    nickname: str | None = None
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class QuotaOut(BaseModel):
    user_id: int
    max_projects: int
    max_files_per_project: int
    max_concurrent_tasks: int
    monthly_token_limit: int
    used_tokens_this_month: int

    model_config = ConfigDict(from_attributes=True)
