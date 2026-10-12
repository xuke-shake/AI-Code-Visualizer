"""2026-10-11 独立报告 R04/R05/R06：真实 API 与本地 Provider。"""
from __future__ import annotations

from io import BytesIO
from threading import Event, Thread
from zipfile import ZipFile

import pytest
from sqlalchemy import event, inspect, select

from app.agents import llm_provider
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.models.analysis_task import AnalysisTask
from app.models.code_chunk import CodeChunk
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.upload import Upload


BASE = "from helpers import greet\ndef target():\n    return greet()\nENTRY = target"
HEAD = "from fastapi import APIRouter\nrouter = APIRouter()\nREQUIRED = 123\nPADDING = " + repr("x" * 14000) + "\n"
TAIL = '\n@router.post("/critical")\ndef critical_route():\n    return REQUIRED\nENTRY = critical_route\n'


def _zip(files):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for path, code in files.items():
            archive.writestr(path, code)
    return buffer.getvalue()


def _upload(client, headers, files):
    response = client.post("/api/uploads", headers=headers, files={"file": ("source.zip", _zip(files), "application/zip")})
    assert response.status_code == 200, response.text
    return response.json()["data"]["upload_id"]


def _setup(client, headers, files=None):
    upload_id = _upload(client, headers, files or {"main.py": BASE, "helpers.py": "def greet():\n    return 'hi'"})
    response = client.post("/api/projects", headers=headers, json={"name": "r04-r06", "source_type": "zip", "upload_id": upload_id})
    assert response.status_code == 200, response.text
    project_id = response.json()["data"]["project"]["id"]
    _parse(client, headers, project_id)
    return project_id, upload_id


def _parse(client, headers, project_id):
    response = client.post(f"/api/projects/{project_id}/parse", headers=headers, json={"mode": "sync"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "success", response.text
    return response


def _analyze(client, headers, project_id, diagram_type="flowchart", selected=None, prompt="分析 target"):
    payload = {"prompt": prompt, "diagram_type": diagram_type}
    if selected is not None:
        payload["parameters"] = {"selectedPaths": selected}
    return client.post(f"/api/projects/{project_id}/analysis", headers=headers, json=payload)


def _provider(monkeypatch, callback=None):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_enabled", "model")
    monkeypatch.setattr(settings, "llm_api_key", "local-test-only")
    calls = []

    class LocalProvider:
        def __init__(self, model, settings):
            pass

        def chat(self, system_prompt, user_prompt):
            calls.append(user_prompt)
            if callback:
                callback(user_prompt)
            # 返回真实规则基线，保留源码节点 ID；不 mock 生成服务或校验器。
            return user_prompt.split("【当前规则生成的基准图，可参考其节点 ID 和结构】\n", 1)[1].split("\n\n【源码上下文】", 1)[0]

    monkeypatch.setattr(llm_provider, "LLMProvider", LocalProvider)
    return calls


def _start(call):
    results = {}

    def run():
        try:
            results["response"] = call()
        except BaseException as exc:
            results["error"] = exc

    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, results


def _finish(worker):
    thread, results = worker
    thread.join(15)
    assert not thread.is_alive(), "测试线程未结束"
    if "error" in results:
        raise results["error"]
    return results["response"]


def _failed_task(client, headers, response, test_database):
    task_id = response.json()["data"]["task_id"]
    queried = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert queried.status_code == 200, queried.text
    assert queried.json()["data"]["status"] == "failed"
    with test_database["session_factory"]() as db:
        task = db.get(AnalysisTask, task_id)
        assert task.status == "failed"
        assert task.progress == 100
        assert task.finished_at is not None
        return task.message


@pytest.mark.parametrize("diagram_type", ["flowchart", "sequence", "state", "architecture"])
def test_r04_long_header_keeps_target_and_module_evidence_in_real_provider(client, auth_header, test_database, monkeypatch, diagram_type):
    source = HEAD + TAIL
    project_id, _ = _setup(client, auth_header, {"route.py": source})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, diagram_type, ["route.py"], "分析 critical_route 路由入口")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "success"
    assert len(calls) == 1
    context = calls[0].split("【源码上下文】\n", 1)[1].rstrip("\n")
    assert len(context) <= 12000
    for evidence in ('@router.post("/critical")', "def critical_route():", "return REQUIRED", "REQUIRED = 123", "router = APIRouter()", "from fastapi import APIRouter", "ENTRY = critical_route"):
        assert evidence in context
    assert context.count("def critical_route():") == 1
    assert "route.py" in context and "行" in context
    assert "省略" in context
    assert "x" * 1000 not in context
    with test_database["session_factory"]() as db:
        module = db.scalar(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == "module"))
        symbol = db.scalar(select(Symbol).where(Symbol.project_id == project_id, Symbol.name == "critical_route"))
        assert module.content == "\n".join(source.splitlines())
        assert symbol.start_line == source.splitlines().index('@router.post("/critical")') + 1
    diagram = client.get(f"/api/diagrams/{response.json()['data']['diagram_id']}", headers=auth_header)
    assert diagram.status_code == 200
    assert "route.py" in diagram.json()["data"]["mermaid_code"]
    if diagram_type in {"flowchart", "architecture"}:
        assert "critical_route" in diagram.json()["data"]["mermaid_code"]


def test_r04_oversized_target_discloses_missing_evidence_with_location(client, auth_header, monkeypatch):
    code = "def critical_route():\n" + "".join(f"    value_{i} = {i}\n" for i in range(1600)) + "    return 123\nENTRY = critical_route"
    project_id, _ = _setup(client, auth_header, {"long.py": code})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, prompt="分析 critical_route")
    assert response.status_code == 200, response.text
    context = calls[0].split("【源码上下文】\n", 1)[1].rstrip("\n")
    assert len(context) <= 12000
    assert "def critical_route():" in context
    assert "证据不足" in context and "省略" in context
    assert "long.py" in context and "行" in context
    assert "省略" in response.json()["data"]["reason"]


@pytest.mark.parametrize("operation", ["unchanged", "modified", "rebuild", "replacement"])
def test_r05_real_sync_or_source_change_overlaps_generation(client, auth_header, test_database, monkeypatch, operation):
    project_id, upload_id = _setup(client, auth_header)
    factory = test_database["session_factory"]
    with factory() as db:
        revision = db.get(Project, project_id).last_index_version
    model_waiting, resume = Event(), Event()

    def waiting(prompt):
        model_waiting.set()
        assert resume.wait(10)

    calls = _provider(monkeypatch, waiting)
    a = _start(lambda: _analyze(client, auth_header, project_id))
    try:
        assert model_waiting.wait(10)
        if operation == "modified":
            # 只改变临时上传内容，真实扫描/增量替换走原服务。
            with factory() as db:
                path = test_database["storage_path"] / db.get(Upload, upload_id).object_key
                assert path.resolve().is_relative_to(test_database["storage_path"].resolve())
                path.write_bytes(_zip({"main.py": BASE.replace("greet()", "greet() + 'changed'"), "helpers.py": "def greet():\n    return 'hi'"}))
        if operation in {"unchanged", "modified"}:
            synced = client.post(f"/api/projects/{project_id}/sync", headers=auth_header, json={"mode": "sync"})
            assert synced.status_code == 200, synced.text
            assert synced.json()["data"]["status"] == "success"
            task = client.get(f"/api/tasks/{synced.json()['data']['task_id']}", headers=auth_header).json()["data"]
            if operation == "unchanged":
                assert task["result_json"]["added"] == task["result_json"]["modified"] == task["result_json"]["deleted"] == []
                assert task["result_json"]["outdated_diagrams"] == 0
            else:
                assert task["result_json"]["modified"] == ["main.py"]
        elif operation == "rebuild":
            _parse(client, auth_header, project_id)
        else:
            new_upload = _upload(client, auth_header, {"new.py": "def replacement():\n    return 456"})
            replaced = client.patch(f"/api/projects/{project_id}", headers=auth_header, json={"upload_id": new_upload})
            assert replaced.status_code == 200, replaced.text
            _parse(client, auth_header, project_id)
        with factory() as db:
            new_revision = db.get(Project, project_id).last_index_version
        resume.set()
        response = _finish(a)
    finally:
        resume.set()
        a[0].join(15)
    assert len(calls) == 1
    # C12: valid same-content full parse retains revision and row identities.
    if operation in {"unchanged", "rebuild"}:
        assert new_revision == revision
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "success"
        with factory() as db:
            assert db.get(Diagram, response.json()["data"]["diagram_id"]).is_outdated is False
    else:
        assert new_revision != revision
        assert response.status_code == 409, response.text
        _failed_task(client, auth_header, response, test_database)
        with factory() as db:
            assert list(db.scalars(select(Diagram).where(Diagram.project_id == project_id))) == []


@pytest.mark.parametrize("invalid", ["no-marker", "legacy-marker", "wrong-source", "no-module", "incomplete-module", "old-decorator-range"])
def test_r05_old_index_cannot_be_relabelled_by_no_change_sync(client, auth_header, test_database, invalid):
    source = 'from fastapi import APIRouter\nrouter = APIRouter()\n@router.get("/x")\ndef target():\n    return 1'
    project_id, upload_id = _setup(client, auth_header, {"main.py": source})
    factory = test_database["session_factory"]
    with factory() as db:
        project = db.get(Project, project_id)
        if invalid in {"no-marker", "legacy-marker", "wrong-source"}:
            project.last_index_version = {"no-marker": None, "legacy-marker": "old-version", "wrong-source": f"upload:{upload_id + 100}:obsolete"}[invalid]
        elif invalid == "no-module":
            for chunk in db.scalars(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == "module")):
                db.delete(chunk)
        elif invalid == "incomplete-module":
            module = db.scalar(select(CodeChunk).where(CodeChunk.project_id == project_id, CodeChunk.chunk_type == "module"))
            module.content = "def target():\n    return 1"
        else:
            symbol = db.scalar(select(Symbol).where(Symbol.project_id == project_id, Symbol.name == "target"))
            symbol.start_line += 1
        db.commit()
        db.refresh(project)
        revision = project.last_index_version
        old_chunks = [tuple(getattr(c, col.key) for col in inspect(CodeChunk).columns) for c in db.scalars(select(CodeChunk).where(CodeChunk.project_id == project_id).order_by(CodeChunk.id))]
    synced = client.post(f"/api/projects/{project_id}/sync", headers=auth_header, json={"mode": "sync"})
    assert synced.status_code == 200, synced.text
    assert synced.json()["data"]["status"] == "failed", synced.text
    queried = client.get(f"/api/tasks/{synced.json()['data']['task_id']}", headers=auth_header)
    assert "全量" in queried.json()["data"]["message"]
    with factory() as db:
        assert db.get(Project, project_id).last_index_version == revision
        assert [tuple(getattr(c, col.key) for col in inspect(CodeChunk).columns) for c in db.scalars(select(CodeChunk).where(CodeChunk.project_id == project_id).order_by(CodeChunk.id))] == old_chunks
    _parse(client, auth_header, project_id)
    assert _analyze(client, auth_header, project_id).status_code == 200


def test_r06_selection_disappears_after_preflight_returns_source_conflict(client, auth_header, test_database, monkeypatch):
    project_id, _ = _setup(client, auth_header)
    new_upload = _upload(client, auth_header, {"new.py": "def replacement():\n    return 456"})
    task_created, release_task = Event(), Event()

    def after_running_commit(conn):
        if conn.info.pop("diagram_task_inserted", False):
            task_created.set()
            assert release_task.wait(10)

    def before_sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("insert into analysis_tasks") and "diagram" in parameters:
            conn.info["diagram_task_inserted"] = True

    engine = test_database["engine"]
    calls = _provider(monkeypatch)
    # commit 事件发生在 sqlite 提交之前，不能在该事件里等 B 提交。
    # 在下一次 SELECT（提交已完成、服务尚未读取项目）处暂停。
    def pause_next_read(conn, cursor, statement, parameters, context, executemany):
        if conn.info.get("diagram_task_inserted") and statement.lstrip().lower().startswith("select"):
            after_running_commit(conn)

    event.listen(engine, "before_cursor_execute", before_sql)
    event.listen(engine, "before_cursor_execute", pause_next_read)
    a = _start(lambda: _analyze(client, auth_header, project_id, selected=["main.py"]))
    try:
        assert task_created.wait(10)
        replaced = client.patch(f"/api/projects/{project_id}", headers=auth_header, json={"upload_id": new_upload})
        assert replaced.status_code == 200, replaced.text
        _parse(client, auth_header, project_id)
        release_task.set()
        response = _finish(a)
    finally:
        release_task.set()
        a[0].join(15)
        event.remove(engine, "before_cursor_execute", before_sql)
        event.remove(engine, "before_cursor_execute", pause_next_read)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == 40900
    assert "源码" in _failed_task(client, auth_header, response, test_database)
    assert calls == []
    with test_database["session_factory"]() as db:
        project = db.get(Project, project_id)
        assert project.repository.upload_id == new_upload and project.status == "ready"
        assert list(db.scalars(select(SourceFile.relative_path).where(SourceFile.project_id == project_id))) == ["new.py"]
        assert list(db.scalars(select(Diagram).where(Diagram.project_id == project_id))) == []


@pytest.mark.parametrize("status,code", [(400, 40000), (422, 42201)])
def test_r06_public_business_error_at_publish_boundary_keeps_contract(client, auth_header, test_database, monkeypatch, status, code):
    project_id, _ = _setup(client, auth_header)
    calls = _provider(monkeypatch)
    message = "本地受控的可公开业务校验失败"

    def reject_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("insert into diagrams"):
            # SQLAlchemy 发布边界故障注入：真实 API/生成/校验/来源守卫均已执行。
            raise AppException(message, code=code, status_code=status)

    event.listen(test_database["engine"], "before_cursor_execute", reject_insert)
    try:
        response = _analyze(client, auth_header, project_id)
    finally:
        event.remove(test_database["engine"], "before_cursor_execute", reject_insert)
    assert len(calls) == 1
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert response.json()["message"] == message
    assert _failed_task(client, auth_header, response, test_database) == message
    with test_database["session_factory"]() as db:
        assert list(db.scalars(select(Diagram).where(Diagram.project_id == project_id))) == []


def test_r06_real_database_error_is_redacted_and_task_queryable(client, auth_header, test_database, monkeypatch):
    project_id, _ = _setup(client, auth_header)
    calls = _provider(monkeypatch)
    secret = "C:/private/server key=private-credential"
    with test_database["engine"].begin() as conn:
        conn.exec_driver_sql("CREATE TRIGGER local_diagram_failure BEFORE INSERT ON diagrams BEGIN SELECT RAISE(ABORT, 'C:/private/server key=private-credential'); END")
    response = _analyze(client, auth_header, project_id)
    assert len(calls) == 1
    assert response.status_code == 500, response.text
    assert response.json()["code"] == 50000
    assert secret not in response.text and "private-credential" not in response.text
    assert "private" not in _failed_task(client, auth_header, response, test_database)
    with test_database["session_factory"]() as db:
        assert list(db.scalars(select(Diagram).where(Diagram.project_id == project_id))) == []


def test_invalid_local_provider_result_still_uses_checked_fallback(client, auth_header, monkeypatch):
    project_id, _ = _setup(client, auth_header)
    calls = _provider(monkeypatch)

    def invalid_chat(self, system_prompt, user_prompt):
        calls.append(user_prompt)
        return 'flowchart TD\n click A "javascript:alert(1)"'

    monkeypatch.setattr(llm_provider.LLMProvider, "chat", invalid_chat)
    response = _analyze(client, auth_header, project_id)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["generation_mode"] == "structural_fallback"
    assert response.json()["data"]["quality_status"] == "degraded"
    assert len(calls) == 1


def test_r04_oversized_single_line_is_omitted_whole_with_explicit_evidence_gap(client, auth_header, monkeypatch):
    code = "def critical_route():\n    return " + repr("y" * 14000) + "\nENTRY = critical_route"
    project_id, _ = _setup(client, auth_header, {"single.py": code})
    calls = _provider(monkeypatch)
    response = _analyze(client, auth_header, project_id, prompt="分析 critical_route")
    assert response.status_code == 200, response.text
    context = calls[0].split("【源码上下文】\n", 1)[1].rstrip("\n")
    assert len(context) <= 12000
    assert "def critical_route():" in context and "ENTRY = critical_route" in context
    assert "证据不足" in context and "省略" in context and "single.py" in context
    assert "y" * 1000 not in context
    assert "return '" not in context  # 不把长字符串截断成伪代码片段。


@pytest.mark.parametrize("newline", ["", "\n", "\r\n"], ids=["no-final-newline", "lf", "crlf"])
def test_r05_unchanged_sync_preserves_revision_for_real_line_endings(client, auth_header, test_database, newline):
    source = BASE if not newline else BASE.replace("\n", newline) + newline
    project_id, _ = _setup(client, auth_header, {"main.py": source})
    factory = test_database["session_factory"]
    with factory() as db:
        revision = db.get(Project, project_id).last_index_version
    synced = client.post(f"/api/projects/{project_id}/sync", headers=auth_header, json={"mode": "sync"})
    assert synced.status_code == 200 and synced.json()["data"]["status"] == "success", synced.text
    task = client.get(f"/api/tasks/{synced.json()['data']['task_id']}", headers=auth_header).json()["data"]
    assert task["result_json"]["modified"] == []
    with factory() as db:
        assert db.get(Project, project_id).last_index_version == revision


def test_r06_runtime_error_at_real_publish_boundary_is_redacted(client, auth_header, test_database, monkeypatch):
    project_id, _ = _setup(client, auth_header)
    calls = _provider(monkeypatch)

    def runtime_failure(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("insert into diagrams"):
            raise RuntimeError("C:/private/path credential=private-token")

    engine = test_database["engine"]
    event.listen(engine, "before_cursor_execute", runtime_failure)
    try:
        response = _analyze(client, auth_header, project_id)
    finally:
        event.remove(engine, "before_cursor_execute", runtime_failure)
    assert len(calls) == 1
    assert response.status_code == 500 and response.json()["code"] == 50000
    assert "private" not in response.text
    assert "private" not in _failed_task(client, auth_header, response, test_database)
    with test_database["session_factory"]() as db:
        assert list(db.scalars(select(Diagram).where(Diagram.project_id == project_id))) == []


def test_r05_missing_module_cannot_be_upgraded_by_change_to_whitespace(client, auth_header, test_database):
    project_id, upload_id = _setup(client, auth_header)
    factory = test_database["session_factory"]
    with factory() as db:
        project = db.get(Project, project_id)
        revision = project.last_index_version
        main = db.scalar(select(SourceFile).where(SourceFile.project_id == project_id, SourceFile.relative_path == "main.py"))
        module = db.scalar(select(CodeChunk).where(CodeChunk.file_id == main.id, CodeChunk.chunk_type == "module"))
        db.delete(module)
        path = test_database["storage_path"] / db.get(Upload, upload_id).object_key
        assert path.resolve().is_relative_to(test_database["storage_path"].resolve())
        path.write_bytes(_zip({"main.py": "   ", "helpers.py": "def greet():\n    return 'hi'"}))
        db.commit()
    response = client.post(f"/api/projects/{project_id}/sync", headers=auth_header, json={"mode": "sync"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "failed"
    with factory() as db:
        assert db.get(Project, project_id).last_index_version == revision
        assert db.scalar(select(Symbol).where(Symbol.project_id == project_id, Symbol.name == "target")) is not None
