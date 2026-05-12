from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.types import BigInt


class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (Index("ix_symbols_project_name", "project_id", "name"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_id: Mapped[int] = mapped_column(BigInt, ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    qualified_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)

    file = relationship("SourceFile", back_populates="symbols")
