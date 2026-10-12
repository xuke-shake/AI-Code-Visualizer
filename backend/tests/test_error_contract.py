from __future__ import annotations

from pathlib import Path
from time import sleep

from app.agents.orchestrator import AgentResult, AnalysisContextSnapshot
from app.agents import orchestrator as orchestrator_module
from app.models.analysis_task import AnalysisTask
from app.models.diagram import Diagram
from app.models.project import Project
from app.services import diagram_service as diagram_service_module



def _create_parsed_project(client, demo_zip, headers, name: str) -> int:
    upload = client.post(
        "/api/uploads",
        headers=headers,
        files={"file": ("demo.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    created = client.post(
        "/api/projects",
        headers=headers,
        json={"name": name, "source_type": "zip", "upload_id": upload.json()["data"]["upload_id"]},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["data"]["project"]["id"]
    parsed = client.post(f"/api/projects/{project_id}/parse", headers=headers, json={"mode": "sync"})
    assert parsed.status_code == 200, parsed.text
    return project_id

def test_register_validation_is_schema_owned_and_has_safe_error_contract(client):
    missing = client.post(
        "/api/auth/register",
        json={"email": "missing-nickname@example.com", "password": "password123"},
        headers={"X-Trace-Id": "trace-register-missing"},
    )
    assert missing.status_code == 422
    assert missing.headers["X-Trace-Id"] == "trace-register-missing"
    body = missing.json()
    assert body["code"] == 42200
    assert body["message"] == "昵称不能为空"
    assert body["trace_id"] == "trace-register-missing"
    assert "detail" not in body

    whitespace = client.post(
        "/api/auth/register",
        json={"email": "whitespace-nickname@example.com", "password": "password123", "nickname": "   "},
    )
    assert whitespace.status_code == 422
    assert whitespace.json()["message"] == "昵称不能为空"

    unsupported = client.post(
        "/api/auth/register",
        json={"email": "extra-field@example.com", "password": "password123", "nickname": "User", "role": "admin"},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["message"] == "请求包含不支持的字段"

    # 未允许的 Origin 不应由错误处理器反射回响应。
    assert "access-control-allow-origin" not in missing.headers


def test_unhandled_error_logs_trace_id_and_hides_internal_details(client, auth_header, demo_zip, monkeypatch, caplog):
    from app.api import projects as projects_api

    upload = client.post(
        "/api/uploads",
        headers=auth_header,
        files={"file": ("demo.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    created = client.post(
        "/api/projects",
        headers=auth_header,
        json={"name": "parse-error", "source_type": "zip", "upload_id": upload.json()["data"]["upload_id"]},
    )
    assert created.status_code == 200, created.text

    def explode(*args, **kwargs):
        raise RuntimeError("C:/private/server/path and internal details")

    monkeypatch.setattr(projects_api.IndexService, "parse_full", explode)
    with caplog.at_level("ERROR"):
        response = client.post(
            f"/api/projects/{created.json()['data']['project']['id']}/parse",
            headers={**auth_header, "X-Trace-Id": "trace-parse-error"},
            json={"mode": "sync"},
        )

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == 50000
    assert body["message"] == "服务器内部错误"
    assert "C:/private" not in response.text
    assert "trace-parse-error" in caplog.text



def test_source_change_during_generation_is_not_published_and_snapshot_is_detached(
    client, demo_zip, auth_header, test_database, monkeypatch
):
    project_id = _create_parsed_project(client, demo_zip, auth_header, "source-race")
    replacement = client.post(
        "/api/uploads",
        headers=auth_header,
        files={"file": ("replacement.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert replacement.status_code == 200, replacement.text
    replacement_id = replacement.json()["data"]["upload_id"]
    session_factory = test_database["session_factory"]

    def compute_while_source_changes(self, *args, **kwargs):
        snapshot = kwargs.get("snapshot")
        assert isinstance(snapshot, AnalysisContextSnapshot)
        assert kwargs.get("db") is None
        assert all(not hasattr(item, "_sa_instance_state") for item in snapshot.source_files)
        sleep(0.05)
        with session_factory() as concurrent_db:
            project = concurrent_db.get(Project, project_id)
            project.repository.upload_id = replacement_id
            project.status = "created"
            project.last_index_version = None
            concurrent_db.commit()
        return AgentResult(
            mermaid_code="\n".join(("flowchart TD", "A[old source] --> B[result]")),
            node_mapping={},
            agent_logs=[],
            generation_mode="structural_fallback",
            reason="test provider",
            quality_status="degraded",
        )

    monkeypatch.setattr(orchestrator_module.AgentOrchestrator, "run_analysis", compute_while_source_changes)
    response = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=auth_header,
        json={"prompt": "生成流程图", "diagram_type": "flowchart"},
    )

    assert response.status_code == 409, response.text
    data = response.json()["data"]
    assert data["status"] == "failed"
    task_id = data["task_id"]
    with session_factory() as db:
        task = db.get(AnalysisTask, task_id)
        assert task.status == "failed"
        assert db.query(Diagram).filter_by(project_id=project_id).count() == 0
        project = db.get(Project, project_id)
        assert project.status == "created"
        assert project.repository.upload_id == replacement_id



def test_publish_guard_serializes_replacement_before_diagram_insert(
    client, demo_zip, auth_header, test_database, monkeypatch
):
    from sqlalchemy import event

    project_id = _create_parsed_project(client, demo_zip, auth_header, "publish-window")
    replacement = client.post(
        "/api/uploads",
        headers=auth_header,
        files={"file": ("replacement.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert replacement.status_code == 200, replacement.text
    replacement_id = replacement.json()["data"]["upload_id"]
    armed = {"value": True, "fired": False}

    def replace_before_publish_guard(conn, cursor, statement, parameters, context, executemany):
        if (
            armed["value"]
            and not armed["fired"]
            and "update projects" in statement.lower()
            and "last_index_version" in statement.lower()
        ):
            armed["fired"] = True
            with test_database["session_factory"]() as concurrent_db:
                project = concurrent_db.get(Project, project_id)
                project.repository.upload_id = replacement_id
                project.status = "created"
                project.last_index_version = None
                concurrent_db.commit()

    event.listen(test_database["engine"], "before_cursor_execute", replace_before_publish_guard)
    try:
        response = client.post(
            f"/api/projects/{project_id}/analysis",
            headers=auth_header,
            json={"prompt": "生成流程图", "diagram_type": "flowchart"},
        )
    finally:
        armed["value"] = False
        event.remove(test_database["engine"], "before_cursor_execute", replace_before_publish_guard)

    assert armed["fired"] is True
    assert response.status_code == 409, response.text
    with test_database["session_factory"]() as db:
        assert db.query(Diagram).filter_by(project_id=project_id).count() == 0
        project = db.get(Project, project_id)
        assert project.repository.upload_id == replacement_id
        assert project.last_index_version is None



def test_generation_exception_is_persisted_and_redacted_after_prevalidation(
    client, demo_zip, auth_header, test_database, monkeypatch
):
    project_id = _create_parsed_project(client, demo_zip, auth_header, "generation-failure")
    session_factory = test_database["session_factory"]
    with session_factory() as db:
        task_count = db.query(AnalysisTask).filter_by(project_id=project_id).count()

    invalid = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=auth_header,
        json={
            "prompt": "无效路径",
            "diagram_type": "flowchart",
            "parameters": {"selectedPaths": ["not-indexed.py"]},
        },
    )
    assert invalid.status_code == 400

    other = client.post(
        "/api/auth/register",
        json={"email": "analysis-forbidden@example.com", "password": "password123", "nickname": "Other"},
    )
    assert other.status_code == 200, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    forbidden = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=other_headers,
        json={"prompt": "无权项目", "diagram_type": "flowchart"},
    )
    assert forbidden.status_code == 403
    with session_factory() as db:
        assert db.query(AnalysisTask).filter_by(project_id=project_id).count() == task_count

    def explode(*args, **kwargs):
        raise RuntimeError("C:/private/server/path and model credentials")

    monkeypatch.setattr(diagram_service_module.DiagramService, "create_analysis", explode)
    response = client.post(
        f"/api/projects/{project_id}/analysis",
        headers={**auth_header, "X-Trace-Id": "trace-diagram-error"},
        json={"prompt": "生成流程图", "diagram_type": "flowchart"},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == 50000
    assert body["data"]["status"] == "failed"
    task_id = body["data"]["task_id"]
    assert "private/server/path" not in response.text
    assert "credentials" not in response.text
    assert body["trace_id"] == "trace-diagram-error"
    tracked = client.get(f"/api/tasks/{task_id}", headers=auth_header)
    assert tracked.status_code == 200
    assert tracked.json()["data"]["status"] == "failed"
    with session_factory() as db:
        task = db.get(AnalysisTask, task_id)
        assert task.message == "图表生成失败，请凭任务编号重试或排查"
        assert task.progress == 100
