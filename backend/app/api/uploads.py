from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.responses import request_trace_id, success
from app.models.user import User
from app.schemas.upload import UploadOut
from app.services.audit_service import AuditService
from app.services.upload_service import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("")
def upload_zip(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = UploadService(db)
    upload = service.create_zip_upload(file, current_user.id)
    data = UploadOut(
        upload_id=upload.id,
        filename=upload.original_filename,
        size_bytes=upload.size_bytes,
        file_count=upload.file_count,
        accepted_source_files=upload.accepted_source_files,
        validation_status=upload.validation_status,
        created_at=upload.created_at,
    ).model_dump(mode="json")
    try:
        AuditService(db).record(current_user.id, "upload.zip", "upload", upload.id, data, request)
        db.commit()
    except Exception:
        db.rollback()
        service._cleanup_new_object(upload.object_key, current_user.id)
        raise
    return success(data, trace_id=request_trace_id(request))
