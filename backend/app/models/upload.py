from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import utc_now
from app.models.types import BigInt


class Upload(Base):
    """已上传的源码包元数据。

    ``object_key`` 是服务端生成的私有存储键，客户端只能持有 upload_id，
    不能通过请求直接指定或读取存储路径。
    """

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_source_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="validated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    owner = relationship("User", back_populates="uploads")
    repositories = relationship("Repository", back_populates="upload")
