from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.responses import request_trace_id, success
from app.models.user import User
from app.services.audit_service import AuditService
from app.tools.zip_safety import save_upload_zip

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("")
async def upload_zip(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    data = await save_upload_zip(file, current_user.id)
    AuditService(db).record(current_user.id, "upload.zip", "upload", None, data, request)
    db.commit()
    return success(data, trace_id=request_trace_id(request))
