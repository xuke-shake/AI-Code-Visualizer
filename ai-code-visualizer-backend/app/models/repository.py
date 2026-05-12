from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.mixins import utc_now
from app.models.types import BigInt


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False)
    repo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zip_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    project = relationship("Project", back_populates="repository")
