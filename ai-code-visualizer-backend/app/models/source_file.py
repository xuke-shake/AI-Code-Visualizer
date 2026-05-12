from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.types import BigInt


class SourceFile(Base, TimestampMixin):
    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("project_id", "relative_path", name="uq_source_files_project_path"),
        Index("ix_source_files_project_hash", "project_id", "file_hash"),
    )

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)

    project = relationship("Project", back_populates="source_files")
    chunks = relationship("CodeChunk", back_populates="file", cascade="all, delete-orphan")
    symbols = relationship("Symbol", back_populates="file", cascade="all, delete-orphan")
