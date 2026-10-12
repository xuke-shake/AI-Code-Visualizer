from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.mixins import utc_now
from app.models.types import BigInt


class Diagram(Base):
    __tablename__ = "diagrams"
    __table_args__ = (Index("ix_diagrams_project_created", "project_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    creator_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    diagram_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    mermaid_code: Mapped[str] = mapped_column(Text, nullable=False)
    node_mapping_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    share_token: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    share_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    project = relationship("Project", back_populates="diagrams")
