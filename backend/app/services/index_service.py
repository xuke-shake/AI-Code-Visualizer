import logging
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analysis_task import AnalysisTask
from app.models.project import Project
from app.models.repository import Repository
from app.parsing import parse_project
from app.parsing.chunker import chunk_and_save
from app.parsing.dependency_analyzer import extract_imports
from app.parsing.file_scanner import scan_zip_inventory
from app.parsing.symbol_extractor import extract_and_save
from app.parsing.tree_parser import parse_source
from app.models.code_chunk import CodeChunk
from app.models.dependency import Dependency
from app.models.diagram import Diagram
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.services.git_service import GitImportError, GitService
from app.services.upload_service import UploadService

logger = logging.getLogger(__name__)



def new_index_revision(project: Project, inventory: dict, upload_id: int | None = None) -> str | None:
    payload = [(path, info["hash"]) for path, info in sorted(inventory.items())]
    # 128 bits of the inventory hash fit the existing 64-character column,
    # even with a 19-digit upload ID. v3 marks the import/scope contract.
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    if project.source_type == "zip":
        upload_id = upload_id if upload_id is not None else (
            project.repository.upload_id if project.repository else None
        )
        if upload_id is None:
            return None
        return f"upload:{upload_id}:v3:{digest}"
    return f"git:v3:{digest}"


def has_current_index(project: Project) -> bool:
    revision = project.last_index_version
    if project.status != "ready" or not revision:
        return False
    if project.source_type == "zip":
        upload_id = project.repository.upload_id if project.repository else None
        return upload_id is not None and revision.startswith(f"upload:{upload_id}:v3:")
    return revision.startswith("git:v3:")

@dataclass(frozen=True)
class IndexFailureSource:
    """失败收尾只能修改操作开始时捕获的来源及索引版本。"""

    source_type: str
    repository_id: int | None
    upload_id: int | None
    zip_object_key: str | None
    prior_revision: str | None
    expected_status: str

    @classmethod
    def capture(cls, project: Project, expected_status: str) -> "IndexFailureSource":
        repository = project.repository
        return cls(
            source_type=project.source_type,
            repository_id=repository.id if repository else None,
            upload_id=repository.upload_id if repository else None,
            zip_object_key=repository.zip_object_key if repository else None,
            prior_revision=project.last_index_version,
            expected_status=expected_status,
        )


class IndexService:
    """源码解析服务，接入 Tree-sitter 解析管线。"""

    def __init__(self, db: Session):
        self.db = db

    def _persist_failed(self, task_id: int, project_id: int, operation: str, exc: Exception | None = None,
                        message: str | None = None, mark_project_failed: bool = True,
                        *, failure_source: IndexFailureSource, diagnostics: list | None = None,
                        retained_old_index: bool | None = None) -> AnalysisTask | None:
        """回滚当前索引事务后，使用独立短事务持久化失败终态。"""

        if exc is not None:
            logger.exception("%s任务异常 project_id=%s task_id=%s", operation, project_id, task_id, exc_info=exc)
        self.db.rollback()
        if retained_old_index is None:
            current = self.db.get(Project, project_id)
            retained_old_index = bool(current and failure_source.prior_revision
                                      and current.last_index_version == failure_source.prior_revision
                                      and self.db.query(SourceFile).filter_by(project_id=project_id).first())
        task = self.db.get(AnalysisTask, task_id)
        if task is not None:
            task.status = "failed"
            task.progress = 100
            task.message = message or f"{operation}失败，请稍后重试"
            task.result_json = {
                "diagnostics": [dict(item) for item in diagnostics or []],
                "retained_old_index": retained_old_index,
            }
            task.finished_at = datetime.now(timezone.utc)
        if mark_project_failed:
            source_matches = exists(
                select(Repository.id).where(
                    Repository.project_id == project_id,
                    Repository.id == failure_source.repository_id,
                    Repository.upload_id == failure_source.upload_id,
                    Repository.zip_object_key == failure_source.zip_object_key,
                )
            )
            if failure_source.repository_id is None:
                source_matches = ~exists(select(Repository.id).where(Repository.project_id == project_id))
            # 同源、同旧版本的新操作也有自己的状态，旧失败任务不能接管它。
            newer_operation = exists(
                select(AnalysisTask.id).where(
                    AnalysisTask.project_id == project_id,
                    AnalysisTask.id > task_id,
                    AnalysisTask.task_type.in_(("parse", "sync")),
                )
            )
            self.db.execute(
                update(Project)
                .where(
                    Project.id == project_id,
                    Project.source_type == failure_source.source_type,
                    source_matches,
                    Project.last_index_version == failure_source.prior_revision,
                    Project.status == failure_source.expected_status,
                    ~newer_operation,
                )
                .values(status="failed")
                .execution_options(synchronize_session="fetch")
            )
        self.db.commit()
        if task is not None:
            self.db.refresh(task)
        return task

    def parse_full(self, project: Project, task: AnalysisTask) -> AnalysisTask:
        task_id = task.id
        project_id = project.id
        failure_source = IndexFailureSource.capture(project, "parsing")
        revision = project.last_index_version or ""
        upload_id = project.repository.upload_id if project.repository else None
        had_current_index = revision.startswith(f"upload:{upload_id}:v3:") if project.source_type == "zip" else revision.startswith("git:v3:")
        retained_old_index = bool(project.last_index_version and self.db.query(SourceFile).filter_by(project_id=project_id).first())

        project.status = "parsing"
        task.status = "running"
        task.progress = 10
        task.message = "正在准备解析"
        self.db.flush()

        settings = get_settings()

        # === 🚀 核心控制：兼容 Git 文件夹（安全过滤 .git 隐藏目录） ===
        snapshot_path: Path | None = None
        indexed_upload_id: int | None = None
        if project.source_type == "git":
            git_service = GitService(settings)
            project_dir = git_service.project_path(project_id)
            if not project_dir.exists():
                self.db.commit()
                return self._persist_failed(
                    task_id, project_id, "解析", message="未找到克隆的 Git 仓库目录",
                    failure_source=failure_source,
                )
            
            try:
                snapshot_path = git_service.pack_snapshot(project_dir, project_id)
                zip_path = snapshot_path
            except GitImportError:
                self.db.commit()
                return self._persist_failed(
                    task_id, project_id, "解析", message="Git仓库快照不可用",
                    failure_source=failure_source,
                )
            
        else:
            # 原本的 ZIP 处理逻辑。旧版本项目可能只有 zip_object_key，先在
            # 受控 storage/uploads/<owner_id> 内完成一次服务端兼容绑定。
            try:
                repository = project.repository
                if repository and repository.upload_id is None and repository.zip_object_key:
                    # Persist the task before a legacy path validation can fail;
                    # _persist_failed then has a durable task to mark failed.
                    self.db.commit()
                    UploadService(self.db).bind_legacy_zip(project, repository)
                repository = project.repository
                if not repository or not repository.upload or repository.upload.validation_status != "validated":
                    self.db.commit()
                    return self._persist_failed(
                        task_id, project_id, "解析", message="未找到上传的 ZIP 文件",
                        failure_source=failure_source,
                    )

                indexed_upload_id = repository.upload_id
                zip_path = settings.storage_path / repository.upload.object_key
                if not zip_path.exists():
                    self.db.commit()
                    return self._persist_failed(
                        task_id, project_id, "解析", message="ZIP 文件不存在",
                        failure_source=replace(failure_source, upload_id=indexed_upload_id),
                    )
            except Exception as exc:
                return self._persist_failed(task_id, project_id, "解析", exc, failure_source=failure_source)
        # ===============================================

        task.progress = 20
        task.message = "正在扫描文件"
        self.db.flush()

        try:
            # 先持久化“正在解析”，让失败任务可追踪；随后来源守卫、旧图失效、
            # 索引替换和版本发布共用一个事务，解析异常时整体回滚旧索引。
            self.db.commit()
            # 兼容绑定已提交后更新来源 ID，原索引版本始终保留操作开始值。
            if indexed_upload_id is not None:
                failure_source = replace(failure_source, upload_id=indexed_upload_id)
                source_matches = exists(
                    select(Repository.id).where(
                        Repository.project_id == project_id,
                        Repository.upload_id == indexed_upload_id,
                    )
                )
                guard = self.db.execute(
                    update(Project)
                    .where(Project.id == project_id, source_matches)
                    .values(status="parsing")
                )
                if guard.rowcount != 1:
                    return self._persist_failed(
                        task_id,
                        project_id,
                        "解析",
                        message="解析期间源码已变化，请重新解析",
                        mark_project_failed=False,
                        failure_source=failure_source,
                    )
            else:
                guard = self.db.execute(
                    update(Project).where(Project.id == project_id, Project.source_type == "git",
                                          Project.last_index_version == failure_source.prior_revision)
                    .values(status="parsing")
                )
                if guard.rowcount != 1:
                    return self._persist_failed(task_id, project_id, "解析", message="解析期间源码已变化，请重新解析",
                                                mark_project_failed=False, failure_source=failure_source)
            existing = {sf.relative_path: sf for sf in self.db.query(SourceFile).filter_by(project_id=project_id)}
            old_hashes = {path: sf.file_hash for path, sf in existing.items()}
            old_contract_valid = had_current_index and self._has_current_chunk_contract(project, {}, existing, require_current=False)
            # Validate/rebuild inside a savepoint, so unchanged valid content can
            # retain row identities referenced by existing diagram mappings.
            rebuild = self.db.begin_nested()
            self._clear_project_index(project_id)
            stats = parse_project(self.db, project_id, Path(zip_path))

        except Exception as exc:
            return self._persist_failed(task_id, project_id, "解析", exc, failure_source=failure_source,
                                        retained_old_index=retained_old_index)
        finally:
            self._cleanup_snapshot(snapshot_path, project_id)

        failed_diagnostics = [
            d for d in getattr(stats, "diagnostics", [])
            if d.get("status") in {"failed", "partial"}
        ]
        if failed_diagnostics:
            return self._persist_failed(
                task_id, project_id, "解析", message=("部分文件解析失败，旧索引已保留" if retained_old_index else "部分文件解析失败，尚未建立可用索引"),
                failure_source=failure_source,
                diagnostics=stats.diagnostics, retained_old_index=retained_old_index,
            )
        if stats["python_files"] == 0:
            return self._persist_failed(
                task_id, project_id, "解析", message="没有可分析的Python源码",
                failure_source=failure_source, diagnostics=stats.diagnostics,
                retained_old_index=retained_old_index,
            )

        unchanged = old_contract_valid and old_hashes == {path: info["hash"] for path, info in stats.inventory.items()}
        if unchanged:
            rebuild.rollback()
        else:
            rebuild.commit()
            self._mark_all_diagrams_outdated(project_id)

        # 成功分支
        task = self.db.get(AnalysisTask, task_id)
        project = self.db.get(Project, project_id)

        if task is None:
            raise RuntimeError(f"解析完成但任务不存在: task_id={task_id}")

        task.status = "success"
        task.progress = 100
        task.message = (
            f"解析完成：文件 {stats['source_files']} 个，"
            f"Python 文件 {stats['python_files']} 个，"
            f"符号 {stats['symbols']} 个，"
            f"代码块 {stats['chunks']} 个，"
            f"依赖 {stats['dependencies']} 条"
        )
        task.finished_at = datetime.now(timezone.utc)
   
        if project:
            project.status = "ready"
            project.file_count = stats["source_files"]
            project.last_index_version = failure_source.prior_revision if unchanged else new_index_revision(project, stats.inventory, indexed_upload_id)
        task.result_json = {
            **dict(stats),
            "diagnostics": getattr(stats, "diagnostics", []),
            "unchanged": unchanged,
        }
 
        self.db.commit()
        self.db.refresh(task)
        return task

    # === 🚀 增量同步增强版 ===
    def sync_incremental(self, project: Project, task: AnalysisTask) -> AnalysisTask:
        task_id = task.id
        project_id = project.id
        failure_source = IndexFailureSource.capture(project, project.status)
        retained_old_index = bool(project.last_index_version and self.db.query(SourceFile).filter_by(project_id=project_id).first())
        diagnostics = []
        snapshot_path: Path | None = None
        indexed_upload_id: int | None = None
        try:
            task.status = "running"
            task.progress = 10
            task.message = "正在对比文件差异"
            self.db.flush()
            # 扫描 Git/ZIP 前先持久化任务运行状态，避免异常回滚把待处理任务一并撤销。
            self.db.commit()

            settings = get_settings()
            if project.source_type == "git":
                git_service = GitService(settings)
                project_dir = git_service.project_path(project.id)
                if not project_dir.exists():
                    return self._persist_failed(task_id, project_id, "同步", message="未找到 Git 仓库目录，无法同步", failure_source=failure_source)
                try:
                    git_service.update_repository(project_dir)
                    snapshot_path = git_service.pack_snapshot(project_dir, project.id)
                    zip_path = snapshot_path
                except GitImportError as exc:
                    return self._persist_failed(task_id, project_id, "同步", exc, "Git远端更新或快照生成失败", failure_source=failure_source)
            else:
                repository = project.repository
                if repository and repository.upload_id is None and repository.zip_object_key:
                    UploadService(self.db).bind_legacy_zip(project, repository)
                repository = project.repository
                if not repository or not repository.upload or repository.upload.validation_status != "validated":
                    return self._persist_failed(task_id, project_id, "同步", message="未找到上传的 ZIP 文件", failure_source=failure_source)
                indexed_upload_id = repository.upload_id
                zip_path = settings.storage_path / repository.upload.object_key
                if not zip_path.exists():
                    return self._persist_failed(task_id, project_id, "同步", message="ZIP 文件不存在", failure_source=failure_source)

            new_files = scan_zip_inventory(zip_path)
            diagnostics = list(getattr(new_files, "diagnostics", []))
            if diagnostics or not any(info["language"] == "python" for info in new_files.values()):
                return self._persist_failed(
                    task_id, project_id, "同步",
                    message="源码编码或扫描失败" if diagnostics else "没有可分析的Python源码",
                    failure_source=failure_source, diagnostics=diagnostics, retained_old_index=retained_old_index,
                )
            if indexed_upload_id is not None:
                source_matches = exists(
                    select(Repository.id).where(
                        Repository.project_id == project_id,
                        Repository.upload_id == indexed_upload_id,
                    )
                )
                guard = self.db.execute(
                    update(Project)
                    .where(Project.id == project_id, source_matches)
                    .values(status=Project.status)
                )
                if guard.rowcount != 1:
                    return self._persist_failed(
                        task_id,
                        project_id,
                        "同步",
                        message="同步期间源码已变化，请重新解析",
                        mark_project_failed=False,
                        failure_source=failure_source,
                    )
            existing = {
                sf.relative_path: sf
                for sf in self.db.query(SourceFile)
                .filter(SourceFile.project_id == project.id)
                .all()
            }
            new_paths = set(new_files.keys())
            old_paths = set(existing.keys())
            added = sorted(new_paths - old_paths)
            deleted = sorted(old_paths - new_paths)
            modified = sorted(
                p for p in (new_paths & old_paths)
                if new_files[p]["hash"] != existing[p].file_hash
            )
            unchanged = sorted(new_paths & old_paths - set(modified))

            # 来源守卫已串行化 ZIP 写入；刷新等待写锁期间可能变化的项目版本。
            self.db.refresh(project)
            if not self._has_current_chunk_contract(project, new_files, existing):
                return self._persist_failed(
                    task_id, project_id, "同步",
                    message="现有索引合同无效，请执行全量解析后使用；增量同步不能代替升级",
                    failure_source=failure_source,
                )
            total_changes = len(added) + len(modified) + len(deleted)
            if total_changes == 0:
                task.status = "success"
                task.progress = 100
                task.message = "没有文件变化"
                task.result_json = {
                    "added": [], "modified": [], "deleted": [],
                    "unchanged": len(unchanged), "outdated_diagrams": 0,
                }
                task.finished_at = datetime.now(timezone.utc)
                self.db.commit()
                self.db.refresh(task)
                return task

            affected_file_ids: set[int] = set()
            task.progress = 20
            task.message = f"处理删除 ({len(deleted)} 个文件)"
            self.db.flush()
            for path in deleted:
                sf = existing[path]
                affected_file_ids.add(sf.id)
                self._delete_file_data(sf.id)
                self.db.delete(sf)
            self.db.flush()

            processed = 0
            total_process = len(added) + len(modified)
            for path in added:
                processed += 1
                if processed % 5 == 0:
                    task.progress = 20 + int(processed / max(total_process, 1) * 40)
                    task.message = f"处理新增 ({processed}/{len(added)})"
                    self.db.flush()
                self._add_or_update_file(project.id, path, new_files[path], diagnostics=diagnostics)

            for path in modified:
                processed += 1
                if processed % 5 == 0:
                    task.progress = 20 + int(processed / max(total_process, 1) * 40)
                    task.message = f"处理修改 ({processed - len(added)}/{len(modified)})"
                    self.db.flush()
                sf = existing[path]
                affected_file_ids.add(sf.id)
                self._delete_file_data(sf.id)
                self._add_or_update_file(project.id, path, new_files[path], source_file=sf, diagnostics=diagnostics)

            self.db.flush()
            task.progress = 70
            task.message = "更新依赖关系"
            self.db.flush()
            self.db.query(Dependency).filter(Dependency.project_id == project.id).delete()
            self.db.flush()

            python_files = [
                sf for sf in self.db.query(SourceFile)
                .filter(SourceFile.project_id == project.id, SourceFile.language == "python")
                .all()
            ]
            known_files = {
                row.relative_path: row.id
                for row in self.db.query(SourceFile).filter(SourceFile.project_id == project.id).all()
            }
            for i, sf in enumerate(python_files):
                if i % 5 == 0:
                    task.progress = 70 + int((i + 1) / max(len(python_files), 1) * 20)
                    task.message = f"更新依赖 ({i + 1}/{len(python_files)})"
                    self.db.flush()
                content = new_files.get(sf.relative_path, {}).get("content")
                if content is not None:
                    extract_imports(self.db, project.id, sf.id, content, known_files=known_files)

            task.progress = 95
            task.message = "检查图表时效"
            self.db.flush()
            outdated_count = self._mark_all_diagrams_outdated(project.id)

            project.status = "ready"
            project.file_count = len(new_paths)
            project.last_index_version = new_index_revision(project, new_files, indexed_upload_id)
            task.status = "success"
            task.progress = 100
            task.message = "增量同步完成"
            task.result_json = {
                "added": added,
                "modified": modified,
                "deleted": deleted,
                "unchanged": len(unchanged),
                "outdated_diagrams": outdated_count,
            }
            task.finished_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(task)
            return task
        except Exception as exc:
            return self._persist_failed(task_id, project_id, "同步", exc, failure_source=failure_source,
                                        diagnostics=diagnostics, retained_old_index=retained_old_index)
        finally:
            self._cleanup_snapshot(snapshot_path, project_id)

    # ── helpers ──
    def _has_current_chunk_contract(self, project: Project, inventory: dict, existing: dict, *, require_current: bool = True) -> bool:
        """核对完整模块和符号范围，旧分块不能靠新 revision 冒充升级。"""
        if require_current and not has_current_index(project):
            return False
        chunks = self.db.scalars(select(CodeChunk).where(CodeChunk.project_id == project.id)).all()
        symbols = self.db.scalars(select(Symbol).where(Symbol.project_id == project.id)).all()
        modules_by_file, contents_by_key, identities_by_file = {}, defaultdict(set), defaultdict(set)
        identity = lambda s: (s.name, s.kind, s.qualified_name, s.start_line, s.end_line)
        for chunk in chunks:
            if chunk.chunk_type == "module":
                modules_by_file.setdefault(chunk.file_id, chunk)
            key = (chunk.file_id, chunk.chunk_type, chunk.symbol_name, chunk.start_line, chunk.end_line)
            contents_by_key[key].add(chunk.content)
        for symbol in symbols:
            identities_by_file[symbol.file_id].add(identity(symbol))

        for path, source_file in existing.items():
            if source_file.language != "python":
                continue
            info = inventory.get(path)
            if source_file.parse_status not in {"parsed", "empty"}:
                return False
            same_file = info is not None and info["hash"] == source_file.file_hash
            if source_file.parse_status == "empty" or (same_file and not info["content"].strip()):
                continue
            module = modules_by_file.get(source_file.id)
            if module is None or module.start_line != 1 or module.end_line != source_file.line_count:
                return False
            # inventory 是原始输入；module 是 chunker 对原始行数组 LF join 后的存储。
            # 对已序列化模块用 split("\n") 还原，不能再次 splitlines 丢失尾空元素。
            lines = info["content"].splitlines() if same_file else module.content.split("\n")
            if module.content != "\n".join(lines) or len(lines) != source_file.line_count:
                return False
            expected = parse_source(module.content)
            if identities_by_file[source_file.id] != {identity(s) for s in expected}:
                return False
            for symbol in expected:
                key = (source_file.id, symbol.kind, symbol.qualified_name or symbol.name,
                       symbol.start_line, symbol.end_line)
                if "\n".join(lines[symbol.start_line - 1:symbol.end_line]) not in contents_by_key.get(key, ()):
                    return False
        return True

    def _clear_project_index(self, project_id: int) -> None:
        """清理某个项目的旧解析索引，供全量解析前使用。"""
        self.db.query(Dependency).filter(
            Dependency.project_id == project_id
        ).delete(synchronize_session="fetch")

        self.db.query(CodeChunk).filter(
            CodeChunk.project_id == project_id
        ).delete(synchronize_session="fetch")

        self.db.query(Symbol).filter(
            Symbol.project_id == project_id
        ).delete(synchronize_session="fetch")

        self.db.query(SourceFile).filter(
            SourceFile.project_id == project_id
        ).delete(synchronize_session="fetch")
        self.db.flush()
        
    def _delete_file_data(self, source_file_id: int) -> None:
        self.db.query(CodeChunk).filter(CodeChunk.file_id == source_file_id).delete()
        self.db.query(Symbol).filter(Symbol.file_id == source_file_id).delete()
        self.db.query(Dependency).filter(
            (Dependency.source_file_id == source_file_id) | (Dependency.target_file_id == source_file_id)
        ).delete()

    def _add_or_update_file(self, project_id: int, relative_path: str, info: dict,
                            source_file: SourceFile | None = None, diagnostics: list | None = None) -> SourceFile:
        sf = source_file or SourceFile(project_id=project_id, relative_path=relative_path)
        sf.project_id = project_id
        sf.relative_path = relative_path
        sf.language = info["language"]
        sf.file_hash = info["hash"]
        sf.size_bytes = info.get("size_bytes", len(info["content"].encode("utf-8")))
        sf.line_count = info.get("line_count", len(info["content"].splitlines()))
        sf.parse_status = "scanned"
        if source_file is None:
            self.db.add(sf)
        self.db.flush()

        if info["language"] != "python":
            sf.parse_status = "skipped"
            return sf

        try:
            symbols = parse_source(info["content"])
        except Exception:
            sf.parse_status = "failed"
            if diagnostics is not None:
                diagnostics.append({"relative_path": relative_path, "language": "python", "status": "failed", "message": "单文件解析失败"})
            self.db.flush()
            raise

        if symbols:
            extract_and_save(self.db, project_id, sf.id, symbols)
            chunk_and_save(self.db, project_id, sf.id, info["content"], symbols)
            sf.parse_status = "parsed"
        else:
            sf.parse_status = "empty" if not info["content"].splitlines() else "parsed"
            if sf.parse_status == "parsed":
                chunk_and_save(self.db, project_id, sf.id, info["content"], symbols)
        self.db.flush()
        return sf

    def _mark_all_diagrams_outdated(self, project_id: int) -> int:
        diagrams = self.db.query(Diagram).filter(Diagram.project_id == project_id).all()
        count = 0
        for diagram in diagrams:
            if not diagram.is_outdated:
                diagram.is_outdated = True
                count += 1
        self.db.flush()
        return count

    def _mark_outdated_diagrams(self, project_id: int, affected_file_ids: set[int]) -> int:
        if not affected_file_ids:
            return 0

        diagrams = self.db.query(Diagram).filter(Diagram.project_id == project_id).all()
        count = 0
        for d in diagrams:
            if d.node_mapping_json and self._json_refers_to(d.node_mapping_json, affected_file_ids):
                d.is_outdated = True
                count += 1

        self.db.flush()
        return count

    @staticmethod
    def _cleanup_snapshot(snapshot_path: Path | None, project_id: int) -> None:
        if snapshot_path is None:
            return
        settings = get_settings()
        storage_root = settings.storage_path.resolve()
        expected_parent = (storage_root / "snapshots" / str(project_id)).resolve()
        try:
            resolved = snapshot_path.resolve(strict=False)
            if resolved.parent != expected_parent or resolved.name in {"", ".", ".."}:
                return
            if not resolved.name.startswith("snapshot-") or resolved.suffix.lower() != ".zip":
                return
            resolved.unlink(missing_ok=True)
        except (OSError, ValueError):
            logger.warning("清理 Git 临时快照失败 path=%s", snapshot_path, exc_info=True)

    @staticmethod
    def _json_refers_to(data, target_ids: set[int]) -> bool:
        if isinstance(data, dict):
            fid = data.get("file_id")
            if fid is not None and fid in target_ids:
                return True
            return any(IndexService._json_refers_to(v, target_ids) for v in data.values())
        if isinstance(data, list):
            return any(IndexService._json_refers_to(v, target_ids) for v in data)
        return False
