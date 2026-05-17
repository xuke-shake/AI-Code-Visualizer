from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.agents.llm_provider import LLMProvider
from app.agents.orchestrator import AgentOrchestrator
from app.core.database import Base
import app.models  # noqa: F401
from app.models.code_chunk import CodeChunk
from app.models.project import Project
from app.models.source_file import SourceFile
from app.models.user import User
from app.tools.mermaid_validator import validate_mermaid


def _build_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def _seed_project(db):
    user = User(email="agent@example.com", password_hash="x")
    db.add(user)
    db.flush()
    project = Project(owner_id=user.id, name="agent-demo", source_type="zip")
    db.add(project)
    db.flush()
    src = SourceFile(project_id=project.id, relative_path="app/auth.py", line_count=30, size_bytes=300)
    db.add(src)
    db.flush()
    db.add_all(
        [
            CodeChunk(
                project_id=project.id,
                file_id=src.id,
                chunk_type="function",
                symbol_name="handle_login",
                start_line=1,
                end_line=8,
                content="def handle_login(): return check_password()",
            ),
            CodeChunk(
                project_id=project.id,
                file_id=src.id,
                chunk_type="function",
                symbol_name="handle_export",
                start_line=10,
                end_line=18,
                content="def handle_export(): return write_file()",
            ),
        ]
    )
    db.commit()
    return project


def test_keyword_retrieval_from_code_chunks():
    db = _build_session()
    project = _seed_project(db)
    orchestrator = AgentOrchestrator(db)

    chunks = orchestrator.retrieve_code_chunks(project.id, ["login"])

    assert chunks
    assert chunks[0].symbol_name == "handle_login"
    db.close()


class BrokenProvider(LLMProvider):
    def generate_mermaid(self, prompt: str, diagram_type: str):
        raise RuntimeError("provider down")


def test_fallback_mermaid_when_model_fails():
    db = _build_session()
    project = _seed_project(db)
    orchestrator = AgentOrchestrator(db, llm_provider=BrokenProvider())

    result = orchestrator.run_analysis(project.id, project.name, "请给我登录流程图", "flowchart")

    assert validate_mermaid(result.mermaid_code).valid
    assert any(log["agent_name"] == "FallbackAgent" for log in result.agent_logs)
    assert any(log.get("status") == "failed" for log in result.agent_logs if log["agent_name"] == "GenerateAgent")
    db.close()
