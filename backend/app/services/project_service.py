import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.agent_run import AgentRun
from app.models.analysis_task import AnalysisTask
from app.models.code_chunk import CodeChunk
from app.models.dependency import Dependency
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.repository import Repository
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.upload import Upload
from app.models.user import User
from app.schemas.project import ProjectConfig, ProjectCreate, ProjectUpdate
from pydantic import ValidationError

DEFAULT_CONFIG = {
    "chunking_strategy": "function",
    "retrieval_top_k": 8,
    "similarity_threshold": 0.35,
    "enable_symbol_search": True,
    "model_name": None,
    "max_tokens": 4000,
}
UNSUPPORTED_CONFIG_KEYS = {
    "enable_symbol_search",
    "chunking_strategy",
    "retrieval_top_k",
    "similarity_threshold",
    "model_name",
    "max_tokens",
}

logger = logging.getLogger(__name__)

PROJECT_ORDER_COLUMNS = {
    "name": Project.name,
    "language": Project.language,
    "status": Project.status,
    "file_count": Project.file_count,
    "created_at": Project.created_at,
    "updated_at": Project.updated_at,
}


class ProjectService:
    def __init__(self, db: Session):
        self.db = db

    def get_owned(self, user: User, project_id: int) -> Project:
        project = self.db.get(Project, project_id)
        if not project:
            raise NotFoundException("项目不存在")
        if user.role != "admin" and project.owner_id != user.id:
            raise ForbiddenException("无权访问该项目")
        return project

    def list_projects(
        self,
        user: User,
        page: int = 1,
        page_size: int = 10,
        keyword: str | None = None,
        language: str | None = None,
        order_by: str = "updated_at",
        order: str = "desc",
    ) -> tuple[list[Project], int]:
        stmt = select(Project).where(Project.owner_id == user.id)
        count_stmt = select(func.count()).select_from(Project).where(Project.owner_id == user.id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(Project.name.ilike(like))
            count_stmt = count_stmt.where(Project.name.ilike(like))
        if language:
            stmt = stmt.where(Project.language == language)
            count_stmt = count_stmt.where(Project.language == language)
        order_key = order_by.value if hasattr(order_by, "value") else str(order_by)
        order_col = PROJECT_ORDER_COLUMNS.get(order_key)
        if order_col is None:
            raise BadRequestException("不支持的项目排序字段")
        stmt = stmt.order_by(order_col.asc() if order == "asc" else order_col.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        return list(self.db.scalars(stmt).all()), int(self.db.scalar(count_stmt) or 0)

    def create_project(self, user: User, payload: ProjectCreate) -> Project:
        upload = None
        if payload.source_type == "zip":
            upload = self._get_owned_validated_upload(user, payload.upload_id)
        config: dict[str, Any]
        if payload.config_json is None:
            config = DEFAULT_CONFIG.copy()
        elif hasattr(payload.config_json, "model_dump"):
            config = payload.config_json.model_dump()
        else:
            config = dict(payload.config_json)
        self._validate_config(config)
        project = Project(
            owner_id=user.id,
            name=payload.name,
            language=payload.language,
            source_type=payload.source_type,
            status="created",
            config_json={**DEFAULT_CONFIG, **config},
        )
        self.db.add(project)
        self.db.flush()
        repo = Repository(
            project_id=project.id,
            repo_url=payload.repo_url,
            branch=payload.branch,
            upload_id=upload.id if upload else None,
        )
        self.db.add(repo)
        # Commit is owned by the request handler together with its audit row.
        self.db.flush()
        return project

    def update_project(self, user: User, project_id: int, payload: ProjectUpdate) -> Project:
        project = self.get_owned(user, project_id)
        data = payload.model_dump(exclude_unset=True)
        upload_id = data.pop("upload_id", None)
        if upload_id is not None:
            upload = self._get_owned_validated_upload(user, upload_id)
            if project.source_type != "zip":
                raise ForbiddenException("仅ZIP项目支持更换上传文件")
            if project.repository is None:
                project.repository = Repository(project_id=project.id)
            if project.repository.upload_id != upload.id:
                project.repository.upload_id = upload.id
                project.repository.zip_object_key = None
                # 显式写入：等待并发解析提交后，也必须覆盖刚发布的旧标记。
                self.db.execute(
                    update(Project)
                    .where(Project.id == project.id)
                    .values(status="created", file_count=0, last_index_version=None)
                    .execution_options(synchronize_session="fetch")
                )
                self.db.execute(
                    update(Diagram)
                    .where(Diagram.project_id == project.id)
                    .values(is_outdated=True)
                )
        if "config_json" in data and data["config_json"] is not None and hasattr(data["config_json"], "model_dump"):
            data["config_json"] = data["config_json"].model_dump()
        if "config_json" in data and data["config_json"] is not None:
            self._validate_config(data["config_json"])
            data["config_json"] = ProjectConfig.model_validate(data["config_json"]).model_dump()
        for key, value in data.items():
            if value is not None:
                setattr(project, key, value)
        self.db.flush()
        return project

    @staticmethod
    def _validate_config(config: dict[str, Any]) -> None:
        unknown = sorted(set(config) - set(DEFAULT_CONFIG))
        if unknown:
            raise BadRequestException(
                "项目配置包含未支持字段: " + ", ".join(unknown)
            )
        try:
            ProjectConfig.model_validate(config)
        except ValidationError as exc:
            raise BadRequestException("项目配置类型或取值无效") from exc
        unsupported = [
            key
            for key in UNSUPPORTED_CONFIG_KEYS
            if key in config and config[key] != DEFAULT_CONFIG[key]
        ]
        if unsupported:
            raise BadRequestException(
                "项目配置参数暂未接入执行链路: " + ", ".join(sorted(unsupported))
            )

    def _get_owned_validated_upload(self, user: User, upload_id: int | None) -> Upload:
        if upload_id is None:
            raise NotFoundException("上传文件不存在")
        upload = self.db.get(Upload, upload_id)
        if not upload:
            raise NotFoundException("上传文件不存在")
        if user.role != "admin" and upload.owner_id != user.id:
            raise ForbiddenException("无权使用该上传文件")
        if upload.validation_status != "validated":
            raise ForbiddenException("上传文件尚未通过校验")
        return upload

    def delete_project(self, user: User, project_id: int) -> None:
        project = self.get_owned(user, project_id)
        repository = project.repository
        upload_candidates: list[Upload] = []
        private_paths: list[Path] = []
        upload_paths: dict[int, Path] = {}

        if repository is not None:
            local_value = repository.local_path or (
                f"projects/{project.id}" if project.source_type == "git" else None
            )
            if local_value:
                path = self._resolve_project_private_path(local_value, "projects", project.id)
                if path is not None:
                    private_paths.append(path)
            if repository.zip_object_key:
                path = self._resolve_private_path(
                    repository.zip_object_key, allowed_roots={"uploads", "snapshots"}
                )
                # 旧键无法证明是本项目私有文件时，不直接递归删除；只有
                # 当前 Upload 无其他引用时才回收其普通文件。
                shared = self.db.query(Repository).filter(
                    Repository.zip_object_key == repository.zip_object_key,
                    Repository.project_id != project.id,
                ).first()
                if path is not None and shared is None and path.is_file():
                    private_paths.append(path)
            if repository.upload_id is not None:
                upload = self.db.get(Upload, repository.upload_id)
                if upload is not None:
                    upload_candidates.append(upload)
                    path = self._resolve_private_path(upload.object_key, allowed_roots={"uploads"})
                    if path is not None:
                        upload_paths[upload.id] = path

            if project.source_type == "git":
                snapshot_dir = self._resolve_project_private_path(
                    f"snapshots/{project.id}", "snapshots", project.id
                )
                if snapshot_dir is not None:
                    private_paths.append(snapshot_dir)

        # 先显式清理没有 ORM relationship 管理的依赖记录，再删除项目主体。
        self.db.query(Dependency).filter(Dependency.project_id == project.id).delete(
            synchronize_session=False
        )
        task_ids = select(AnalysisTask.id).where(AnalysisTask.project_id == project.id)
        self.db.query(AgentRun).filter(AgentRun.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
        self.db.query(CodeChunk).filter(CodeChunk.project_id == project.id).delete(
            synchronize_session=False
        )
        self.db.query(Symbol).filter(Symbol.project_id == project.id).delete(
            synchronize_session=False
        )
        self.db.query(SourceFile).filter(SourceFile.project_id == project.id).delete(
            synchronize_session=False
        )
        self.db.query(Diagram).filter(Diagram.project_id == project.id).delete(
            synchronize_session=False
        )
        self.db.query(Repository).filter(Repository.project_id == project.id).delete(
            synchronize_session=False
        )
        self.db.query(AnalysisTask).filter(AnalysisTask.project_id == project.id).delete(
            synchronize_session=False
        )
        self.db.query(Project).filter(Project.id == project.id).delete(synchronize_session=False)

        # Upload 是用户级私有资源，只有确认不再被任何仓库引用时才回收。
        for upload in upload_candidates:
            still_referenced = self.db.query(Repository).filter(Repository.upload_id == upload.id).first()
            if still_referenced is None:
                self.db.delete(upload)
                upload_path = upload_paths.get(upload.id)
                if upload_path is not None:
                    private_paths.append(upload_path)
        self.db.commit()

        # 数据库提交成功后再清理文件；任何路径都必须来自数据库字段并位于受控私有目录。
        for path in private_paths:
            self._remove_private_path(path)

    @staticmethod
    def _resolve_private_path(value: str, allowed_roots: set[str]) -> Path | None:
        """仅解析数据库确认且位于 storage 私有子目录中的路径。"""

        settings = get_settings()
        storage_root = settings.storage_path.resolve()
        raw = Path(value)
        candidate = raw if raw.is_absolute() else storage_root / raw
        try:
            resolved = candidate.resolve(strict=False)
            relative = resolved.relative_to(storage_root)
        except (OSError, ValueError):
            logger.warning("拒绝清理越界私有路径: %s", value)
            return None
        if not relative.parts or relative.parts[0] not in allowed_roots:
            logger.warning("拒绝清理未授权私有路径: %s", value)
            return None
        current = storage_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                logger.warning("拒绝清理包含符号链接的私有路径: %s", value)
                return None
        return resolved

    @staticmethod
    def _resolve_project_private_path(value: str, root_name: str, project_id: int) -> Path | None:
        resolved = ProjectService._resolve_private_path(value, allowed_roots={root_name})
        if resolved is None:
            return None
        settings = get_settings()
        try:
            relative = resolved.relative_to(settings.storage_path.resolve())
        except (OSError, ValueError):
            return None
        if relative.parts != (root_name, str(project_id)):
            logger.warning("拒绝清理其他项目私有目录: %s", value)
            return None
        return resolved

    @staticmethod
    def _remove_private_path(path: Path) -> None:
        try:
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError:
            logger.warning("私有文件清理失败 path=%s", path, exc_info=True)

    def create_task(self, user: User, project: Project, task_type: str, message: str | None = None) -> AnalysisTask:
        task = AnalysisTask(
            project_id=project.id,
            user_id=user.id,
            task_type=task_type,
            status="pending",
            progress=0,
            message=message,
        )
        self.db.add(task)
        self.db.flush()
        return task
