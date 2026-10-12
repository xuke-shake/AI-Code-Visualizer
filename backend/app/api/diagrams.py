from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.responses import request_trace_id, success
from app.models.user import User
from app.schemas.diagram import DiagramOut, DiagramUpdate, ExportOut, ExportRequest, ShareOut, ShareRequest
from app.services.diagram_service import DiagramService
from app.services.export_service import ExportService

router = APIRouter(prefix="/diagrams", tags=["diagrams"])


@router.get("/{diagram_id}")
def get_diagram(diagram_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    diagram = DiagramService(db).get_diagram(current_user, diagram_id)
    data = DiagramService(db).serialize_diagram(diagram)
    return success(DiagramOut.model_validate(data).model_dump(), trace_id=request_trace_id(request))


@router.patch("/{diagram_id}")
def update_diagram(diagram_id: int, payload: DiagramUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    diagram = DiagramService(db).update_diagram(current_user, diagram_id, payload)
    data = DiagramService(db).serialize_diagram(diagram)
    return success(DiagramOut.model_validate(data).model_dump(), trace_id=request_trace_id(request))


@router.post("/{diagram_id}/export")
def export_diagram(diagram_id: int, payload: ExportRequest, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    diagram = DiagramService(db).get_diagram(current_user, diagram_id)
    data = ExportService(db).export_diagram(diagram, payload.format, payload.filename)
    return success(ExportOut(**data).model_dump(), trace_id=request_trace_id(request))


@router.get("/{diagram_id}/export/{filename}")
def download_export(
    diagram_id: int,
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载当前用户有权访问的单个图表导出文件。"""

    diagram = DiagramService(db).get_diagram(current_user, diagram_id)
    service = ExportService(db)
    path = service.resolve_export_path(diagram, filename)
    return FileResponse(path=path, media_type=service.media_type(path), filename=path.name)


@router.post("/{diagram_id}/share")
def share_diagram(diagram_id: int, payload: ShareRequest, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    diagram, token = DiagramService(db).share(current_user, diagram_id, payload.expire_hours)
    data = ShareOut(share_url=f"/share/{token}", share_token=token, expires_at=diagram.share_expires_at).model_dump()
    return success(data, trace_id=request_trace_id(request))


@router.post("/{diagram_id}/refresh")
def refresh_diagram(diagram_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    diagram = DiagramService(db).get_diagram(current_user, diagram_id)
    if diagram.is_outdated:
        raise HTTPException(status_code=409, detail="图表已过期，请重新生成后再使用")
    data = DiagramService(db).serialize_diagram(diagram)
    return success(DiagramOut.model_validate(data).model_dump(), trace_id=request_trace_id(request))
