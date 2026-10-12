from __future__ import annotations

from datetime import datetime, timezone

from app.agents.orchestrator import AgentOrchestrator
from app.core.config import Settings
from app.models.dependency import Dependency
from app.models.project import Project
from app.models.source_file import SourceFile
from app.models.user import User
from app.services.project_service import ProjectService
from app.schemas.project import ProjectUpdate
from app.core.exceptions import BadRequestException
from app.services.admin_service import AdminService
from app.schemas.admin import QuotaUpdate
from app.parsing.dependency_analyzer import extract_imports
from app.parsing.tree_parser import parse_source


def _project(db_session):
    user = User(
        email="bugfix-regression@example.com",
        password_hash="unused",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    project = Project(owner_id=user.id, name="regression", source_type="zip", status="ready")
    db_session.add(project)
    db_session.flush()
    return project


def test_relative_imports_resolve_exact_modules_and_ambiguous_modules_stay_unresolved(db_session):
    project = _project(db_session)
    source = SourceFile(project_id=project.id, relative_path="pkg/sub/main.py", language="python")
    helper = SourceFile(project_id=project.id, relative_path="pkg/sub/helper.py", language="python")
    root = SourceFile(project_id=project.id, relative_path="pkg/root.py", language="python")
    package = SourceFile(project_id=project.id, relative_path="pkg/__init__.py", language="python")
    package_helper = SourceFile(project_id=project.id, relative_path="pkg/package_helper.py", language="python")
    duplicate_a = SourceFile(project_id=project.id, relative_path="a/utils.py", language="python")
    duplicate_b = SourceFile(project_id=project.id, relative_path="b/utils.py", language="python")
    db_session.add_all([source, helper, root, package, package_helper, duplicate_a, duplicate_b])
    db_session.flush()

    ids = extract_imports(
        db_session,
        project.id,
        source.id,
        "from . import helper\nfrom .. import root\nfrom pkg import package_helper\nimport utils\n",
    )
    deps = db_session.query(Dependency).filter(Dependency.id.in_(ids)).all()
    targets = [dependency.target_file_id for dependency in deps]
    assert helper.id in targets
    assert root.id in targets
    assert package_helper.id in targets
    assert targets[-1] is None


def test_async_symbol_identity_and_module_context_are_preserved():
    symbols = parse_source("@router.get(\"/run\")\nasync def run():\n    return 1\n")
    assert [(symbol.name, symbol.qualified_name) for symbol in symbols] == [("run", "run")]
    assert symbols[0].start_line == 1
    assert symbols[0].end_line == 3


def test_state_repair_keeps_quoted_edge_annotation():
    repaired = AgentOrchestrator(Settings(llm_enabled="off"))._repair_state_diagram(
        'stateDiagram-v2\n    "未登录" --> "已登录": "进入"\n'
    )
    assert ': "进入"' in repaired
    assert 'state "未登录" as S1' in repaired


def test_unsupported_project_execution_config_is_rejected(db_session):
    project = _project(db_session)
    try:
        ProjectService(db_session).update_project(
            User(id=project.owner_id, role="user"),
            project.id,
            ProjectUpdate(config_json={"retrieval_top_k": 12}),
        )
    except BadRequestException as exc:
        assert "retrieval_top_k" in exc.message
    else:
        raise AssertionError("未接入执行链路的配置不应静默保存")

    try:
        ProjectService(db_session)._validate_config({"future_option": True})
    except BadRequestException as exc:
        assert "future_option" in exc.message
    else:
        raise AssertionError("未知项目配置不应被静默保存")


def test_quota_updates_are_explicitly_disabled(db_session):
    try:
        AdminService(db_session).update_quota(1, QuotaUpdate(max_projects=10))
    except BadRequestException as exc:
        assert "未启用" in exc.message
    else:
        raise AssertionError("未启用的配额扣减接口不应返回成功")
