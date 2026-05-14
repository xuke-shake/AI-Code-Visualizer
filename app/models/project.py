from sqlalchemy import BigInteger, ForeignKey, Integer, JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.types import BigInt


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_owner_updated", "owner_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # git/zip
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_index_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)

    owner = relationship("User", back_populates="projects")
    repository = relationship("Repository", back_populates="project", cascade="all, delete-orphan", uselist=False)
    source_files = relationship("SourceFile", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("AnalysisTask", back_populates="project", cascade="all, delete-orphan")
    diagrams = relationship("Diagram", back_populates="project", cascade="all, delete-orphan")
