from fastapi import Request
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        user_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: int | None = None,
        detail: dict | None = None,
        request: Request | None = None,
    ) -> AuditLog:
        ip = None
        if request and request.client:
            ip = request.client.host
        log = AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip,
            detail_json=detail or {},
        )
        self.db.add(log)
        self.db.flush()
        return log
