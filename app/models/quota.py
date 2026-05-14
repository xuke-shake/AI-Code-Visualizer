from sqlalchemy import BigInteger, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.types import BigInt


class Quota(Base):
    __tablename__ = "quotas"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    max_projects: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    max_files_per_project: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    monthly_token_limit: Mapped[int] = mapped_column(Integer, default=500000, nullable=False)
    used_tokens_this_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user = relationship("User", back_populates="quota")
