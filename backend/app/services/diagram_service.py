from datetime import datetime, timezone, timedelta
from secrets import token_urlsafe
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session
from app.agents.orchestrator import (
    AgentOrchestrator,
    AnalysisContextSnapshot,
    CodeChunkContext,
    SourceFileContext,
    SymbolContext,
)
from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException, AppException
from app.models.agent_run import AgentRun
from app.models.analysis_task import AnalysisTask
from app.models.code_chunk import CodeChunk
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.repository import Repository
from app.models.user import User
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.services.index_service import has_current_index
from app.schemas.diagram import AnalysisCreate, DiagramUpdate
from app.tools.mermaid_validator import validate_mermaid


class DiagramService:
    def __init__(self, db: Session):
        self.db = db

    def get_diagram(self, user: User, diagram_id: int) -> Diagram:
        diagram = self.db.get(Diagram, diagram_id)
        if not diagram:
            raise NotFoundException("图表不存在")
        project = self.db.get(Project, diagram.project_id)
        if not project or (user.role != "admin" and project.owner_id != user.id):
            raise ForbiddenException("无权访问该图表")
        return diagram

    def serialize_diagram(self, diagram: Diagram) -> dict:
        data = {
            "id": diagram.id,
            "project_id": diagram.project_id,
            "creator_id": diagram.creator_id,
            "title": diagram.title,
            "diagram_type": diagram.diagram_type,
            "prompt": diagram.prompt,
            "mermaid_code": diagram.mermaid_code,
            "node_mapping_json": diagram.node_mapping_json,
            "version": diagram.version,
            "is_outdated": diagram.is_outdated,
            "created_at": diagram.created_at,
            "generation_mode": None,
            "quality_status": None,
            "generation_reason": None,
        }
        task = (
            self.db.query(AnalysisTask)
            .filter(AnalysisTask.project_id == diagram.project_id, AnalysisTask.task_type == "diagram")
            .order_by(AnalysisTask.created_at.desc())
            .all()
        )
        for candidate in task:
            metadata = candidate.result_json if isinstance(candidate.result_json, dict) else {}
            if metadata.get("diagram_id") != diagram.id:
                continue
            data["generation_mode"] = metadata.get("generation_mode")
            data["quality_status"] = metadata.get("quality_status")
            data["generation_reason"] = metadata.get("reason")
            break
        if diagram.version > 1:
            data["generation_mode"] = "edited"
            data["quality_status"] = None
            data["generation_reason"] = "编辑后的图表；原始生成来源仅供参考"
        return data

    def create_analysis(
        self,
        user_id: int,
        project_id: int,
        task_id: int,
        payload: AnalysisCreate,
        *,
        expected_source: tuple[str | None, int | None] | None = None,
    ) -> Diagram:
        project = self.db.get(Project, project_id)
        if project is None or not has_current_index(project):
            raise ConflictException("当前源码尚未完成解析，请先解析后生成")

        project_name = project.name
        source_revision = project.last_index_version
        upload_id = project.repository.upload_id if project.repository else None
        if expected_source is not None and (source_revision, upload_id) != expected_source:
            raise ConflictException("生成准备期间源码已变化，请重新选择文件后重试")
        scope_paths = None
        if payload.parameters and "selectedPaths" in payload.parameters:
            raw_paths = payload.parameters.get("selectedPaths")
            if raw_paths is not None:
                scope_paths = list(raw_paths)
                if not scope_paths:
                    raise AppException("请至少选择一个已解析文件")

        source_files = (
            self.db.query(SourceFile)
            .filter(SourceFile.project_id == project_id)
            .order_by(SourceFile.relative_path.asc())
            .all()
        )
        known_paths = {source_file.relative_path for source_file in source_files}
        if scope_paths is not None and set(scope_paths) - known_paths:
            if expected_source is not None:
                raise ConflictException("生成准备期间源码或所选文件已变化，请重新选择文件后重试")
            raise AppException("所选文件不属于项目已解析文件")
        file_ids = [source_file.id for source_file in source_files]
        symbols = (
            self.db.query(Symbol)
            .filter(Symbol.project_id == project_id, Symbol.file_id.in_(file_ids))
            .order_by(Symbol.file_id.asc(), Symbol.start_line.asc(), Symbol.name.asc())
            .all()
            if file_ids
            else []
        )
        chunks = (
            self.db.query(CodeChunk)
            .filter(CodeChunk.project_id == project_id, CodeChunk.file_id.in_(file_ids))
            .order_by(CodeChunk.file_id.asc(), CodeChunk.start_line.asc())
            .all()
            if file_ids
            else []
        )
        snapshot = AnalysisContextSnapshot(
            source_files=tuple(
                SourceFileContext(
                    id=item.id,
                    relative_path=item.relative_path,
                    language=item.language,
                    line_count=item.line_count,
                    file_hash=item.file_hash,
                )
                for item in source_files
            ),
            symbols=tuple(
                SymbolContext(
                    id=item.id,
                    file_id=item.file_id,
                    name=item.name,
                    kind=item.kind,
                    qualified_name=item.qualified_name,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    signature=item.signature,
                )
                for item in symbols
            ),
            chunks=tuple(
                CodeChunkContext(
                    id=item.id,
                    file_id=item.file_id,
                    chunk_type=item.chunk_type,
                    symbol_name=item.symbol_name,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    content=item.content,
                )
                for item in chunks
            ),
        )
        self.db.rollback()

        orchestrator = AgentOrchestrator()
        result = orchestrator.run_analysis(
            project_name,
            payload.prompt,
            payload.diagram_type,
            scope_paths=scope_paths,
            snapshot=snapshot,
        )
        validation = validate_mermaid(result.mermaid_code, expected_type=payload.diagram_type)
        if not validation.valid:
            raise AppException("Mermaid校验失败: " + "; ".join(validation.errors))

        # The first write in this short transaction is a conditional source guard.
        # SQLite serializes this write with a concurrent upload replacement; the
        # diagram and task outcome are committed in the same transaction.
        source_matches = True
        if upload_id is not None:
            source_matches = exists(
                select(Repository.id).where(
                    Repository.project_id == project_id,
                    Repository.upload_id == upload_id,
                )
            )
        guard = self.db.execute(
            update(Project)
            .where(
                Project.id == project_id,
                Project.status == "ready",
                Project.last_index_version == source_revision,
                source_matches,
            )
            .values(status="ready")
        )
        if guard.rowcount != 1:
            self.db.rollback()
            raise ConflictException("生成期间源码已变化，本次结果未发布，请重新解析后重试")

        diagram = Diagram(
            project_id=project_id,
            creator_id=user_id,
            title=payload.title or payload.prompt[:40],
            diagram_type=payload.diagram_type,
            prompt=payload.prompt,
            mermaid_code=result.mermaid_code,
            node_mapping_json=result.node_mapping,
            version=1,
            is_outdated=False,
        )
        self.db.add(diagram)
        self.db.flush()
        for item in result.agent_logs:
            self._record_agent_run(task_id, item)
        task = self.db.get(AnalysisTask, task_id)
        if task is None:
            raise RuntimeError(f"分析任务不存在: task_id={task_id}")
        task.status = "success"
        task.progress = 100
        task.message = "图表生成成功"
        task.result_json = {
            "diagram_id": diagram.id,
            "generation_mode": result.generation_mode,
            "reason": result.reason,
            "quality_status": result.quality_status,
        }
        task.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(diagram)
        return diagram
    
    def _record_agent_run(self, task_id: int, item: dict) -> None:
        """兼容 agent 日志格式，并转换成 agent_runs 表字段。"""
        error = item.get("errors") or item.get("error_message")
        duration_sec = item.get("duration_sec")
        latency_ms = item.get("latency_ms")

        if latency_ms is None and duration_sec is not None:
            try:
                latency_ms = int(float(duration_sec) * 1000)
            except (TypeError, ValueError):
                latency_ms = 0

        self.db.add(
            AgentRun(
                task_id=task_id,
                agent_name=(item.get("agent_name") or "UnknownAgent")[:64],
                input_summary=item.get("input_summary"),
                output_summary=item.get("output_summary"),
                model_name=item.get("model_name"),
                prompt_tokens=item.get("prompt_tokens") or 0,
                completion_tokens=item.get("completion_tokens") or 0,
                usage_collected=item.get("usage_collected") is True,
                latency_ms=latency_ms or 0,
                status="failed" if error else item.get("status", "success"),
                error_message=error,
            )
        )

    def update_diagram(self, user: User, diagram_id: int, payload: DiagramUpdate) -> Diagram:
        diagram = self.get_diagram(user, diagram_id)
        data = payload.model_dump(exclude_unset=True)
        if "node_mapping_json" in data:
            raise BadRequestException("源码映射由服务端维护")
        if "mermaid_code" in data and data["mermaid_code"]:
            result = validate_mermaid(data["mermaid_code"], expected_type=diagram.diagram_type)
            if not result.valid:
                raise AppException("Mermaid语法错误: " + "; ".join(result.errors))
            if data["mermaid_code"] != diagram.mermaid_code:
                diagram.version += 1
                # Mermaid edited outside the indexed source is no longer backed by
                # the previous source mapping.  Never keep stale file/line links.
                diagram.node_mapping_json = None
                data.pop("node_mapping_json", None)
        for key, value in data.items():
            if value is not None:
                setattr(diagram, key, value)
        self.db.commit()
        self.db.refresh(diagram)
        return diagram

    def share(self, user: User, diagram_id: int, expire_hours: int) -> tuple[Diagram, str]:
        diagram = self.get_diagram(user, diagram_id)
        token = token_urlsafe(32)
        diagram.share_token = token
        diagram.share_expires_at = datetime.now(timezone.utc) + timedelta(hours=expire_hours)
        self.db.commit()
        self.db.refresh(diagram)
        return diagram, token
