from datetime import datetime, timezone, timedelta
from secrets import token_urlsafe
from sqlalchemy.orm import Session
from app.agents.orchestrator import AgentOrchestrator
from app.core.exceptions import ForbiddenException, NotFoundException, AppException
from app.models.agent_run import AgentRun
from app.models.analysis_task import AnalysisTask
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.user import User
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

    def create_analysis(self, user: User, project: Project, task: AnalysisTask, payload: AnalysisCreate) -> Diagram:
        task.status = "running"
        task.progress = 30
        task.message = "正在执行Agent分析"
        orchestrator = AgentOrchestrator()
        scope_paths = []
        if payload.parameters and isinstance(payload.parameters, dict):
            scope_paths = payload.parameters.get("selectedPaths") or []
        result = orchestrator.run_analysis(
            project.name,
            payload.prompt,
            payload.diagram_type,
            db=self.db,
            project_id=project.id,
            scope_paths=scope_paths,
        )
        validation = validate_mermaid(result.mermaid_code)
        if not validation.valid:
            raise AppException("Mermaid校验失败: " + "; ".join(validation.errors))
        diagram = Diagram(
            project_id=project.id,
            creator_id=user.id,
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
            self._record_agent_run(task.id, item)
        task.status = "success"
        task.progress = 100
        task.message = "图表生成成功"
        task.result_json = {"diagram_id": diagram.id}
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
                latency_ms=latency_ms or 0,
                status="failed" if error else item.get("status", "success"),
                error_message=error,
            )
        )

    def update_diagram(self, user: User, diagram_id: int, payload: DiagramUpdate) -> Diagram:
        diagram = self.get_diagram(user, diagram_id)
        data = payload.model_dump(exclude_unset=True)
        if "mermaid_code" in data and data["mermaid_code"]:
            result = validate_mermaid(data["mermaid_code"])
            if not result.valid:
                raise AppException("Mermaid语法错误: " + "; ".join(result.errors))
            diagram.version += 1
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
