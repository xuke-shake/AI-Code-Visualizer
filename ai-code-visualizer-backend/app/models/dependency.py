from decimal import Decimal
from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.types import BigInt


class Dependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = (Index("ix_dependencies_project_source_symbol", "project_id", "source_symbol_id"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_symbol_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True)
    target_symbol_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True)
    source_file_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True)
    target_file_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("source_files.id", ondelete="SET NULL"), nullable=True)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
