from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.types import BigInt


class CodeChunk(Base):
    __tablename__ = "code_chunks"
    __table_args__ = (Index("ix_code_chunks_project_file", "project_id", "file_id"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_id: Mapped[int] = mapped_column(BigInt, ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    file = relationship("SourceFile", back_populates="chunks")
