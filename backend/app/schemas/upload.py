from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UploadOut(BaseModel):
    upload_id: int
    filename: str
    size_bytes: int
    file_count: int
    accepted_source_files: int
    validation_status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
