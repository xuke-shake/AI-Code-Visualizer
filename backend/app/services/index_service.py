from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analysis_task import AnalysisTask
from app.models.project import Project
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


class IndexService:
    """源码解析服务，接入 Tree-sitter 解析管线。"""

    def __init__(self, db: Session):
        self.db = db

    def parse_full(self, project: Project, task: AnalysisTask) -> AnalysisTask:
        task_id = task.id
        project_id = project.id

        project.status = "parsing"
        task.status = "running"
        task.progress = 10
        task.message = "正在准备解析"
        self.db.flush()

        repository = project.repository

        if not repository or not repository.zip_object_key:
            task.status = "failed"
            task.message = "未找到上传的 ZIP 文件"
            task.finished_at = datetime.now(timezone.utc)
            project.status = "failed"
            self.db.commit()
            self.db.refresh(task)
            return task

        settings = get_settings()
        zip_path = settings.storage_path / repository.zip_object_key
        if not zip_path.exists():
            task.status = "failed"
            task.message = f"ZIP 文件不存在: {repository.zip_object_key}"
            task.finished_at = datetime.now(timezone.utc)
            project.status = "failed"
            self.db.commit()
            self.db.refresh(task)
            return task

        task.progress = 20
        task.message = "正在扫描文件"
        self.db.flush()

        try:
        # 全量解析前先清理旧索引，避免重复解析同一个项目时 source_files 唯一键冲突
            self._clear_project_index(project_id)
    
            stats = parse_project(self.db, project_id, Path(zip_path))

        except Exception as exc:
            self.db.rollback()

            task = self.db.get(AnalysisTask, task_id)
            project = self.db.get(Project, project_id)

            if task:
                task.status = "failed"
                task.progress = 100
                task.message = f"解析失败: {exc}"
                task.finished_at = datetime.now(timezone.utc)

            if project:
                project.status = "failed"
    
            self.db.commit()

            if task:
                self.db.refresh(task)

            return task

    # 这里是你原来缺失的成功分支
        task = self.db.get(AnalysisTask, task_id)
        project = self.db.get(Project, project_id)

        if task is None:
            raise RuntimeError(f"解析完成但任务不存在: task_id={task_id}")

        task.status = "success"
        task.progress = 100
        task.message = (
            f"解析完成：文件 {stats.get('files', 0)} 个，"
            f"符号 {stats.get('symbols', 0)} 个，"
            f"代码块 {stats.get('chunks', 0)} 个，"
            f"依赖 {stats.get('dependencies', 0)} 条"
        )
        task.finished_at = datetime.now(timezone.utc)
   
        if project:
            project.status = "ready"
 
        self.db.commit()
        self.db.refresh(task)
        return task


#检查新增代码块
    def sync_incremental(self, project: Project, task: AnalysisTask) -> AnalysisTask:
        task.status = "running"
        task.progress = 10
        task.message = "正在对比文件差异"
        self.db.flush()

        repository = project.repository
        if not repository or not repository.zip_object_key:
            task.status = "failed"
            task.message = "未找到上传的 ZIP 文件"
            task.finished_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(task)
            return task

        settings = get_settings()
        zip_path = settings.storage_path / repository.zip_object_key
        if not zip_path.exists():
            task.status = "failed"
            task.message = f"ZIP 文件不存在: {repository.zip_object_key}"
            task.finished_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(task)
            return task

        # 1. 只读扫描新 ZIP，与 DB 现有文件做 diff
        new_files = scan_zip_inventory(zip_path)
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

        total_changes = len(added) + len(modified) + len(deleted)
        if total_changes == 0:
            #打个时间戳标签
            project.last_index_version = f"idx-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            task.status = "success"
            task.progress = 100
            task.message = "没有文件变化"
            task.result_json = {"added": [], "modified": [], "deleted": [], "outdated_diagrams": 0}
            task.finished_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(task)
            return task

        affected_file_ids: set[int] = set()

        # 2. 处理删除
        task.progress = 20
        task.message = f"处理删除 ({len(deleted)} 个文件)"
        self.db.flush()
        for path in deleted:
            sf = existing[path]
            affected_file_ids.add(sf.id)
            self._delete_file_data(sf.id)

        # 3. 处理新增 + 修改
        processed = 0
        total_process = len(added) + len(modified)
        for path in added:
            processed += 1
            if processed % 5 == 0:
                task.progress = 20 + int(processed / max(total_process, 1) * 40)
                task.message = f"处理新增 ({processed}/{len(added)})"
                self.db.flush()
            self._add_or_update_file(project.id, path, new_files[path])

        for path in modified:
            processed += 1
            if processed % 5 == 0:
                task.progress = 20 + int(processed / max(total_process, 1) * 40)
                task.message = f"处理修改 ({processed - len(added)}/{len(modified)})"
                self.db.flush()
            sf = existing[path]
            affected_file_ids.add(sf.id)
            self._delete_file_data(sf.id)
            self.db.delete(sf)
            self.db.flush()
            self._add_or_update_file(project.id, path, new_files[path])

        self.db.flush()

        # 4. 重建所有依赖
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
        for i, sf in enumerate(python_files):
            if i % 5 == 0:
                task.progress = 70 + int((i + 1) / max(len(python_files), 1) * 20)
                task.message = f"更新依赖 ({i + 1}/{len(python_files)})"
                self.db.flush()
            content = new_files.get(sf.relative_path, {}).get("content")
            if content:
                try:
                    extract_imports(self.db, project.id, sf.id, content)
                except Exception:
                    pass

        # 5. 标记过时图表
        task.progress = 95
        task.message = "检查图表时效"
        self.db.flush()
        outdated_count = self._mark_outdated_diagrams(project.id, affected_file_ids)

        project.status = "ready"
        project.file_count = len(new_paths)
        #打个时间戳标签
        project.last_index_version = f"idx-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
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

    # ── helpers ──
    def _clear_project_index(self, project_id: int) -> None:
        """清理某个项目的旧解析索引，供全量解析前使用。"""
        self.db.query(Dependency).filter(
            Dependency.project_id == project_id
        ).delete(synchronize_session=False)

        self.db.query(CodeChunk).filter(
            CodeChunk.project_id == project_id
        ).delete(synchronize_session=False)

        self.db.query(Symbol).filter(
            Symbol.project_id == project_id
        ).delete(synchronize_session=False)

        self.db.query(SourceFile).filter(
            SourceFile.project_id == project_id
        ).delete(synchronize_session=False)
        self.db.flush()
        
    def _delete_file_data(self, source_file_id: int) -> None:
        self.db.query(CodeChunk).filter(CodeChunk.file_id == source_file_id).delete()
        self.db.query(Symbol).filter(Symbol.file_id == source_file_id).delete()
        self.db.query(Dependency).filter(
            (Dependency.source_file_id == source_file_id) | (Dependency.target_file_id == source_file_id)
        ).delete()

    def _add_or_update_file(self, project_id: int, relative_path: str, info: dict) -> None:
        sf = SourceFile(
            project_id=project_id,
            relative_path=relative_path,
            language=info["language"],
            file_hash=info["hash"],
            size_bytes=len(info["content"].encode("utf-8")),
            line_count=info["content"].count("\n"),
            parse_status="scanned",
        )
        self.db.add(sf)
        self.db.flush()

        if info["language"] != "python":
            return

        try:
            symbols = parse_source(info["content"])
        except Exception:
            return

        if symbols:
            extract_and_save(self.db, project_id, sf.id, symbols)
            chunk_and_save(self.db, project_id, sf.id, info["content"], symbols)

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
    def _json_refers_to(data, target_ids: set[int]) -> bool:
        if isinstance(data, dict):
            fid = data.get("file_id")
            sid = data.get("symbol_id")
            if (fid is not None and fid in target_ids) or (sid is not None and sid in target_ids):
                return True
            return any(IndexService._json_refers_to(v, target_ids) for v in data.values())
        if isinstance(data, list):
            return any(IndexService._json_refers_to(v, target_ids) for v in data)
        return False
