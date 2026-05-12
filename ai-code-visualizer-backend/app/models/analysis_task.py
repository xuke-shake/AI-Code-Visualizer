from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.mixins import utc_now
from app.models.types import BigInt


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"
    __table_args__ = (Index("ix_analysis_tasks_project_status_created", "project_id", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="tasks")
    agent_runs = relationship("AgentRun", back_populates="task", cascade="all, delete-orphan")
