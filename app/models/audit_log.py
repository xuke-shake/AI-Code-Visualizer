from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.mixins import utc_now
from app.models.types import BigInt


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_user_action_created", "user_id", "action", "created_at"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInt, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
