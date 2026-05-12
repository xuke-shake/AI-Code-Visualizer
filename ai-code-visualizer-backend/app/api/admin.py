from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.responses import request_trace_id, success
from app.models.analysis_task import AnalysisTask
from app.models.audit_log import AuditLog
from app.models.quota import Quota
from app.models.user import User
from app.schemas.admin import AuditLogOut, MetricsOut, QuotaUpdate, UserWithQuota
from app.schemas.common import Page
from app.schemas.task import TaskOut
from app.schemas.user import QuotaOut, UserOut
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/metrics")
def metrics(request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    return success(MetricsOut(**AdminService(db).metrics()).model_dump(), trace_id=request_trace_id(request))


@router.get("/users")
def users(request: Request, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100), keyword: str | None = None, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    stmt = select(User).order_by(User.created_at.desc())
    count_stmt = select(func.count()).select_from(User)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(User.email.ilike(like))
        count_stmt = count_stmt.where(User.email.ilike(like))
    rows = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())
    total = int(db.scalar(count_stmt) or 0)
    items = []
    for user in rows:
        quota = db.scalar(select(Quota).where(Quota.user_id == user.id))
        items.append(UserWithQuota(user=UserOut.model_validate(user), quota=QuotaOut.model_validate(quota) if quota else None))
    return success(Page[UserWithQuota](items=items, total=total, page=page, page_size=page_size).model_dump(), trace_id=request_trace_id(request))


@router.get("/tasks")
def tasks(request: Request, status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    stmt = select(AnalysisTask).order_by(AnalysisTask.created_at.desc())
    count_stmt = select(func.count()).select_from(AnalysisTask)
    if status:
        stmt = stmt.where(AnalysisTask.status == status)
        count_stmt = count_stmt.where(AnalysisTask.status == status)
    rows = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())
    total = int(db.scalar(count_stmt) or 0)
    data = Page[TaskOut](items=[TaskOut.model_validate(row) for row in rows], total=total, page=page, page_size=page_size).model_dump()
    return success(data, trace_id=request_trace_id(request))


@router.patch("/quotas/{user_id}")
def update_quota(user_id: int, payload: QuotaUpdate, request: Request, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    quota = AdminService(db).update_quota(user_id, payload)
    return success(QuotaOut.model_validate(quota).model_dump(), trace_id=request_trace_id(request))


@router.get("/audit-logs")
def audit_logs(request: Request, action: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    count_stmt = select(func.count()).select_from(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    rows = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())
    total = int(db.scalar(count_stmt) or 0)
    data = Page[AuditLogOut](items=[AuditLogOut.model_validate(row) for row in rows], total=total, page=page, page_size=page_size).model_dump()
    return success(data, trace_id=request_trace_id(request))
