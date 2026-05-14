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
        result = orchestrator.run_analysis(project.name, payload.prompt, payload.diagram_type)
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
            self.db.add(AgentRun(task_id=task.id, status="success", **item))
        task.status = "success"
        task.progress = 100
        task.message = "图表生成成功"
        task.result_json = {"diagram_id": diagram.id}
        task.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(diagram)
        return diagram

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
