from __future__ import annotations

from datetime import datetime, timezone

from app.agents.orchestrator import AgentOrchestrator, AgentResult
from app.core.config import Settings
from app.models.analysis_task import AnalysisTask
from app.models.project import Project
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.code_chunk import CodeChunk
from app.models.user import User
from app.services import diagram_service as diagram_service_module
from app.services.diagram_service import DiagramService
from app.schemas.diagram import AnalysisCreate
from app.tools.mermaid_validator import validate_mermaid


def test_fallback_is_explicit_and_never_platform_workflow():
    result = AgentOrchestrator(Settings(llm_enabled="off")).run_analysis(
        "repo", "生成业务图", "flowchart"
    )

    assert result.generation_mode == "structural_fallback"
    assert result.quality_status == "degraded"
    assert result.reason
    assert "结构降级视图" in result.mermaid_code
    assert "FastAPI" not in result.mermaid_code
    assert validate_mermaid(result.mermaid_code).valid
    assert any("generation_mode=structural_fallback" in item["output_summary"] for item in result.agent_logs)


def test_rule_sequence_and_class_diagrams_do_not_invent_edges():
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    first = SourceFile(id=1, project_id=1, relative_path="a.py", line_count=3)
    second = SourceFile(id=2, project_id=1, relative_path="b.py", line_count=3)

    sequence, _ = orchestrator._build_sequence_diagram("repo", "prompt", [first, second], [], [])
    classes, _ = orchestrator._build_class_diagram("repo", "prompt", [first, second], [], [])
    flowchart, _ = orchestrator._build_flowchart("repo", "prompt", [first], [], [])

    assert "调用或依赖" not in sequence
    assert "->>" not in sequence
    assert " ..> " not in classes
    assert "结构包含视图" in flowchart


def test_no_evidence_with_database_is_degraded_and_explains_reason(db_session):
    now = datetime.now(timezone.utc)
    user = User(email="p1-14@example.com", password_hash="unused", created_at=now)
    db_session.add(user)
    db_session.flush()
    project = Project(owner_id=user.id, name="empty", source_type="zip", status="ready")
    db_session.add(project)
    db_session.flush()
    db_session.add(SourceFile(project_id=project.id, relative_path="empty.py", line_count=0))
    db_session.commit()

    result = AgentOrchestrator(Settings(llm_enabled="off")).run_analysis(
        project.name, "生成业务图", "flowchart", db=db_session, project_id=project.id
    )

    assert result.generation_mode == "structural_fallback"
    assert result.quality_status == "degraded"
    assert "没有可用的符号或代码块" in result.reason
    assert validate_mermaid(result.mermaid_code).valid


def test_diagram_service_persists_generation_metadata(db_session, monkeypatch):
    now = datetime.now(timezone.utc)
    user = User(email="p1-14-service@example.com", password_hash="unused", created_at=now)
    db_session.add(user)
    db_session.flush()
    project = Project(owner_id=user.id, name="service", source_type="git", status="ready", last_index_version="git:v3:test")
    db_session.add(project)
    db_session.flush()
    task = AnalysisTask(project_id=project.id, user_id=user.id, task_type="diagram", status="pending")
    db_session.add(task)
    db_session.commit()

    expected = AgentResult(
        mermaid_code="flowchart TD\n    A[\"结构视图\"]",
        node_mapping={"A": {"file_path": "a.py", "start_line": 1, "end_line": 1, "code": ""}},
        agent_logs=[{"agent_name": "TestAgent", "output_summary": "degraded"}],
        generation_mode="structural_fallback",
        reason="测试：证据不足",
        quality_status="degraded",
    )

    class FakeOrchestrator:
        def run_analysis(self, *args, **kwargs):
            return expected

    monkeypatch.setattr(diagram_service_module, "AgentOrchestrator", FakeOrchestrator)
    diagram = DiagramService(db_session).create_analysis(
        user.id,
        project.id,
        task.id,
        AnalysisCreate(prompt="生成结构图", diagram_type="flowchart"),
    )

    assert task.result_json == {
        "diagram_id": diagram.id,
        "generation_mode": "structural_fallback",
        "reason": "测试：证据不足",
        "quality_status": "degraded",
    }
    assert len(task.agent_runs) == 1
    assert task.agent_runs[0].agent_name == "TestAgent"


def test_p1_15_mapping_has_stable_identity_and_real_evidence():
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    first = SourceFile(
        id=11,
        project_id=7,
        relative_path="src/a.py",
        file_hash="a" * 64,
        line_count=8,
    )
    second = SourceFile(
        id=12,
        project_id=7,
        relative_path="src/b.py",
        file_hash="b" * 64,
        line_count=8,
    )
    first_symbol = Symbol(
        id=101,
        project_id=7,
        file_id=11,
        name="run",
        kind="function",
        qualified_name="run",
        start_line=2,
        end_line=4,
        signature="def run():",
    )
    duplicate_name = Symbol(
        id=102,
        project_id=7,
        file_id=12,
        name="run",
        kind="function",
        qualified_name="run",
        start_line=2,
        end_line=4,
        signature="def run():",
    )
    first_chunk = CodeChunk(
        id=201,
        project_id=7,
        file_id=11,
        symbol_name="run",
        chunk_type="function",
        start_line=2,
        end_line=4,
        content="def run():\n    return 1",
    )

    mermaid, mapping = orchestrator._build_flowchart(
        "repo", "prompt", [first, second], [first_symbol, duplicate_name], [first_chunk]
    )

    stable_keys = [key for key in mapping if key.startswith("Sym_")]
    assert len(stable_keys) == 2
    assert stable_keys[0] != stable_keys[1]
    evidence = mapping[stable_keys[0]]
    assert evidence["file_id"] in {11, 12}
    assert evidence["symbol_id"] in {101, 102}
    assert evidence["file_hash"] in {"a" * 64, "b" * 64}
    assert evidence["file_path"] in {"src/a.py", "src/b.py"}
    assert evidence["start_line"] == 2
    assert evidence["end_line"] == 4
    assert "unresolved" not in evidence or evidence["unresolved"] is False
    assert "Sym_" in mermaid


def test_p1_15_unresolved_llm_node_never_gets_fake_location():
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    mapping = {}
    result = orchestrator._augment_mapping_for_mermaid(
        "flowchart TD\n    NewNode[\"generated\"]", mapping, "secret context"
    )

    assert result["NewNode"]["unresolved"] is True
    assert result["NewNode"]["file_path"] is None
    assert result["NewNode"]["start_line"] is None
    assert result["NewNode"]["end_line"] is None
    assert result["NewNode"]["code"] == ""
    assert "参考上下文" not in str(result["NewNode"])


def test_p1_15_find_chunk_prefers_identity_and_smallest_range():
    orchestrator = AgentOrchestrator(Settings(llm_enabled="off"))
    symbol = Symbol(
        id=1,
        project_id=1,
        file_id=1,
        name="run",
        kind="function",
        qualified_name="Service.run",
        start_line=3,
        end_line=4,
    )
    broad = CodeChunk(
        id=1,
        project_id=1,
        file_id=1,
        symbol_name="container",
        chunk_type="class",
        start_line=1,
        end_line=8,
        content="class Service: ...",
    )
    exact = CodeChunk(
        id=2,
        project_id=1,
        file_id=1,
        symbol_name="Service.run",
        chunk_type="method",
        start_line=3,
        end_line=4,
        content="def run(): ...",
    )

    assert orchestrator._find_chunk_for_symbol(symbol, [broad, exact]) is exact
