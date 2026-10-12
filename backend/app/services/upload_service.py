import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.models.project import Project
from app.models.repository import Repository
from app.models.upload import Upload
from app.tools.zip_safety import save_upload_zip_sync, validate_zip_file


class UploadService:
    def __init__(self, db: Session):
        self.db = db

    def create_zip_upload(self, upload: UploadFile, owner_id: int) -> Upload:
        info = save_upload_zip_sync(upload, owner_id)
        object_key = info["object_key"]
        record = Upload(
            owner_id=owner_id,
            object_key=info["object_key"],
            original_filename=info["filename"],
            size_bytes=info["size_bytes"],
            file_count=info["file_count"],
            accepted_source_files=info["accepted_source_files"],
            validation_status="validated",
        )
        self.db.add(record)
        try:
            self.db.flush()
        except Exception:
            self.db.rollback()
            self._cleanup_new_object(object_key, owner_id)
            raise
        return record

    @staticmethod
    def _cleanup_new_object(object_key: str, owner_id: int) -> None:
        settings = get_settings()
        root = settings.storage_path.resolve()
        candidate = (root / object_key).resolve(strict=False)
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return
        if relative.parts[:2] != ("uploads", str(owner_id)) or candidate.is_dir():
            return
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            import logging
            logging.getLogger(__name__).warning("上传补偿清理失败 path=%s", candidate, exc_info=True)

    def bind_legacy_zip(self, project: Project, repository: Repository | None = None) -> Upload | None:
        """将旧版本 repository.zip_object_key 安全迁移为 Upload 记录。

        旧记录只允许引用 storage/uploads/<owner_id>/ 下的已有文件。迁移会
        重新执行 ZIP 校验，并复制到服务端新生成的对象键；客户端不能通过
        请求参数指定旧路径或新对象键。
        """

        repository = repository or project.repository
        if repository is None:
            return None
        if repository.upload_id is not None:
            return repository.upload
        if not repository.zip_object_key:
            return None

        settings = get_settings()
        storage_root = settings.storage_path.resolve()
        raw = Path(repository.zip_object_key)
        candidate = raw if raw.is_absolute() else storage_root / raw
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(storage_root)
        except (OSError, ValueError) as exc:
            raise AppException("旧 ZIP 路径不在受控上传目录内") from exc

        if (
            not resolved.is_file()
            or len(relative.parts) < 3
            or relative.parts[0] != "uploads"
            or relative.parts[1] != str(project.owner_id)
            or candidate.is_symlink()
        ):
            raise AppException("旧 ZIP 路径不在当前用户的受控上传目录内")

        # 检查路径上的每一段，拒绝通过父目录符号链接绕出 storage/uploads。
        current = storage_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise AppException("旧 ZIP 路径包含符号链接")

        info = validate_zip_file(resolved)
        upload_dir = storage_root / "uploads" / str(project.owner_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        object_key = f"uploads/{project.owner_id}/{uuid4().hex}.zip"
        target = storage_root / object_key
        temp_target = upload_dir / f".legacy-{uuid4().hex}.tmp"
        try:
            shutil.copyfile(resolved, temp_target)
            os.replace(temp_target, target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            temp_target.unlink(missing_ok=True)

        record = Upload(
            owner_id=project.owner_id,
            object_key=object_key,
            original_filename=resolved.name,
            size_bytes=resolved.stat().st_size,
            file_count=info["file_count"],
            accepted_source_files=info["accepted_source_files"],
            validation_status="validated",
        )
        try:
            self.db.add(record)
            self.db.flush()
            repository.upload_id = record.id
            repository.upload = record
            self.db.flush()
        except Exception:
            self.db.rollback()
            target.unlink(missing_ok=True)
            raise
        return record
