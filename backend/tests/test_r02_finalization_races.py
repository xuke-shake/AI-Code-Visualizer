"""2026-10-11 独立报告 R02-A/B：真实 API、独立连接及可控线程时序。"""
from __future__ import annotations

from io import BytesIO
from threading import Event, Thread
from zipfile import ZipFile

import pytest
from sqlalchemy import event, inspect, select

from app.models.analysis_task import AnalysisTask
from app.models.audit_log import AuditLog
from app.models.code_chunk import CodeChunk
from app.models.dependency import Dependency
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.upload import Upload
from app.services.audit_service import AuditService
from app.services import index_service as index_module
from app.services.index_service import IndexService
from app.services.project_service import ProjectService


def _zip_bytes(entry):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("main.py", f"from helpers import greet\ndef {entry}():\n    return greet()\nVALUE = '{entry}'\n")
        archive.writestr("helpers.py", "def greet():\n    return 'hello'\n")
    return buffer.getvalue()


def _setup(client, headers):
    uploads = []
    for entry in ("old_entry", "new_entry"):
        response = client.post("/api/uploads", headers=headers, files={"file": (f"{entry}.zip", _zip_bytes(entry), "application/zip")})
        assert response.status_code == 200, response.text
        uploads.append(response.json()["data"]["upload_id"])
    response = client.post("/api/projects", headers=headers, json={"name": "R02 races", "source_type": "zip", "upload_id": uploads[0]})
    assert response.status_code == 200, response.text
    return response.json()["data"]["project"]["id"], uploads


def _parse(client, headers, project_id):
    response = client.post(f"/api/projects/{project_id}/parse", headers=headers, json={"mode": "sync"})
    assert response.status_code == 200, response.text
    return response


def _analyze(client, headers, project_id):
    return client.post(f"/api/projects/{project_id}/analysis", headers=headers, json={"prompt": "根据当前源码生成图", "diagram_type": "flowchart"})


def _replace(client, headers, project_id, upload_id):
    response = client.patch(f"/api/projects/{project_id}", headers=headers, json={"upload_id": upload_id})
    assert response.status_code == 200, response.text
    return response


def _start(call):
    result = {}

    def run():
        try:
            result["response"] = call()
        except BaseException as exc:
            result["error"] = exc

    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, result


def _finish(worker):
    thread, result = worker
    thread.join(15)
    assert not thread.is_alive(), "并发测试线程未结束（可能发生死锁）"
    if "error" in result:
        raise result["error"]
    return result["response"]


def _index_rows(db, project_id):
    # 包括主键、哈希、源码块内容及依赖，而非仅比较数量。
    return {
        model.__tablename__: [tuple(getattr(row, column.key) for column in inspect(model).columns)
                              for row in db.scalars(select(model).where(model.project_id == project_id).order_by(model.id))]
        for model in (SourceFile, Symbol, CodeChunk, Dependency)
    }


def _assert_new_index(db, project_id, upload_id, entry):
    project = db.get(Project, project_id)
    assert project.repository.upload_id == upload_id
    assert project.status == "ready"
    assert project.last_index_version.startswith(f"upload:{upload_id}:")
    assert project.file_count == 2
    names = set(db.scalars(select(Symbol.name).where(Symbol.project_id == project_id)))
    assert entry in names
    assert ("old_entry" if entry == "new_entry" else "new_entry") not in names
    rows = _index_rows(db, project_id)
    assert all(rows.values()), "新索引的文件/符号/源码块/依赖均应存在"
    return project.last_index_version, rows


def test_r02_a_parse_holds_lock_then_real_replacement_resets_all_metadata(client, auth_header, test_database, monkeypatch):
    project_id, uploads = _setup(client, auth_header)
    factory = test_database["session_factory"]
    with factory() as db:
        project = db.get(Project, project_id)
        for title in ("old flow", "old state"):
            db.add(Diagram(project_id=project_id, creator_id=project.owner_id, title=title,
                           diagram_type="flowchart", mermaid_code="flowchart TD\nA-->B", is_outdated=False))
        db.commit()

    a_locked, b_first_write = Event(), Event()
    connections, observed = {}, {}
    real_parse, real_update = index_module.parse_project, ProjectService.update_project

    def held_parse(db, pid, zip_path):
        connections["A"] = id(db.connection().connection.driver_connection)
        a_locked.set()
        # 只等待 B 已读取并开始写入，绝不等待 B 提交。
        assert b_first_write.wait(10), "B 未开始等待写锁"
        return real_parse(db, pid, zip_path)

    def observed_update(self, user, pid, payload):
        project = self.get_owned(user, pid)
        observed["before"] = (project.last_index_version, project.file_count)
        assert observed["before"] == (None, 0)
        conn = self.db.connection()
        connections["B"] = id(conn.connection.driver_connection)
        conn.info["r02_replacement"] = True
        try:
            return real_update(self, user, pid, payload)
        finally:
            conn.info.pop("r02_replacement", None)

    def before_write(conn, cursor, statement, parameters, context, executemany):
        if conn.info.get("r02_replacement") and statement.lstrip().lower().startswith("update"):
            b_first_write.set()

    monkeypatch.setattr(index_module, "parse_project", held_parse)
    monkeypatch.setattr(ProjectService, "update_project", observed_update)
    event.listen(test_database["engine"], "before_cursor_execute", before_write)
    a = _start(lambda: _parse(client, auth_header, project_id))
    b = None
    try:
        assert a_locked.wait(10)
        b = _start(lambda: _replace(client, auth_header, project_id, uploads[1]))
        parsed = _finish(a)
        replaced = _finish(b)
    finally:
        b_first_write.set()
        a[0].join(15)
        if b:
            b[0].join(15)
        event.remove(test_database["engine"], "before_cursor_execute", before_write)
    assert connections["A"] != connections["B"]
    assert parsed.json()["data"]["status"] == "success"
    assert replaced.json()["data"]["status"] == "created"
    assert replaced.json()["data"]["last_index_version"] is None
    assert replaced.json()["data"]["file_count"] == 0
    with factory() as db:
        project = db.get(Project, project_id)
        assert (project.repository.upload_id, project.status, project.last_index_version, project.file_count) == (uploads[1], "created", None, 0)
        assert all(d.is_outdated for d in db.scalars(select(Diagram).where(Diagram.project_id == project_id)))
        assert db.scalar(select(AuditLog).where(AuditLog.action == "project.update")) is not None
    assert _analyze(client, auth_header, project_id).status_code == 409


@pytest.mark.parametrize("same_upload", [False, True], ids=["new-source", "same-upload-same-content"])
@pytest.mark.parametrize("failure", ["exception", "diagnostic", "sync"], ids=["full-exception", "full-diagnostic", "sync-exception"])
def test_r02_b_old_failure_preserves_new_success(client, auth_header, test_database, monkeypatch, same_upload, failure):
    project_id, uploads = _setup(client, auth_header)
    assert _parse(client, auth_header, project_id).json()["data"]["status"] == "success"
    factory = test_database["session_factory"]
    with factory() as db:
        old_revision = db.get(Project, project_id).last_index_version

    rolled_back, allow_finalization, intercepted = Event(), Event(), Event()
    real_parse = index_module.parse_project
    real_scan = index_module.scan_zip_inventory
    real_failed = IndexService._persist_failed
    observed = {}

    def failed_parse(*args, **kwargs):
        if not intercepted.is_set():
            intercepted.set()
            if failure == "exception":
                raise RuntimeError("controlled local failure")
            stats = real_parse(*args, **kwargs)
            stats.diagnostics.append({"status": "partial", "path": "main.py"})
            return stats
        return real_parse(*args, **kwargs)

    def failed_scan(*args, **kwargs):
        if not intercepted.is_set():
            intercepted.set()
            raise RuntimeError("controlled sync failure")
        return real_scan(*args, **kwargs)

    def pause_after_rollback(self, task_id, *args, **kwargs):
        self.db.rollback()
        observed["old_task_id"] = task_id
        rolled_back.set()
        assert allow_finalization.wait(10), "B 尚未完成新解析"
        return real_failed(self, task_id, *args, **kwargs)

    monkeypatch.setattr(index_module, "parse_project", failed_parse)
    if failure == "sync":
        # 同步准备失败也是同类收尾，且不先破坏旧索引。
        monkeypatch.setattr(index_module, "scan_zip_inventory", failed_scan)
        monkeypatch.setattr(index_module, "parse_project", real_parse)
    monkeypatch.setattr(IndexService, "_persist_failed", pause_after_rollback)
    a = _start(lambda: client.post(f"/api/projects/{project_id}/{'sync' if failure == 'sync' else 'parse'}", headers=auth_header, json={"mode": "sync"}))
    try:
        assert rolled_back.wait(10)
        if not same_upload:
            _replace(client, auth_header, project_id, uploads[1])
        new_upload = uploads[0 if same_upload else 1]
        assert _parse(client, auth_header, project_id).json()["data"]["status"] == "success"
        with factory() as db:
            new_revision, new_rows = _assert_new_index(db, project_id, new_upload, "old_entry" if same_upload else "new_entry")
        # C12: unchanged content keeps its revision; newer task identity still
        # prevents the old failure from taking over the new successful parse.
        assert (new_revision == old_revision) is same_upload
        allow_finalization.set()
        failed = _finish(a)
    finally:
        allow_finalization.set()
        a[0].join(15)
    assert failed.status_code == 200, failed.text
    assert failed.json()["data"]["status"] == "failed"
    tracked = client.get(f"/api/tasks/{observed['old_task_id']}", headers=auth_header)
    assert tracked.status_code == 200, tracked.text
    assert tracked.json()["data"]["status"] == "failed"
    with factory() as db:
        assert _assert_new_index(db, project_id, new_upload, "old_entry" if same_upload else "new_entry") == (new_revision, new_rows)
        assert db.get(AnalysisTask, observed["old_task_id"]).status == "failed"
    generated = _analyze(client, auth_header, project_id)
    assert generated.status_code == 200, generated.text
    assert generated.json()["data"]["status"] == "success"
    diagram = client.get(f"/api/diagrams/{generated.json()['data']['diagram_id']}", headers=auth_header)
    assert diagram.status_code == 200, diagram.text
    assert ("old_entry" if same_upload else "new_entry") in diagram.json()["data"]["mermaid_code"]


def test_failure_rolls_back_complete_index_and_diagrams(client, auth_header, test_database, monkeypatch):
    project_id, _ = _setup(client, auth_header)
    assert _parse(client, auth_header, project_id).json()["data"]["status"] == "success"
    generated = _analyze(client, auth_header, project_id)
    assert generated.status_code == 200, generated.text
    diagram_id = generated.json()["data"]["diagram_id"]
    factory = test_database["session_factory"]
    with factory() as db:
        old_rows = _index_rows(db, project_id)
        old_revision = db.get(Project, project_id).last_index_version

    def fail(*args, **kwargs):
        raise RuntimeError("rollback whole index")

    monkeypatch.setattr(index_module, "parse_project", fail)
    failed = _parse(client, auth_header, project_id)
    assert failed.json()["data"]["status"] == "failed"
    with factory() as db:
        assert db.get(Project, project_id).status == "failed"
        assert db.get(Project, project_id).last_index_version == old_revision
        assert _index_rows(db, project_id) == old_rows
        assert db.get(Diagram, diagram_id).is_outdated is False
    assert _analyze(client, auth_header, project_id).status_code == 409


def test_publish_first_then_real_replacement_marks_published_diagram_outdated(client, auth_header, test_database, monkeypatch):
    project_id, uploads = _setup(client, auth_header)
    assert _parse(client, auth_header, project_id).json()["data"]["status"] == "success"
    publish_locked, replacement_attempted = Event(), Event()
    real_update = ProjectService.update_project

    def observed_update(self, user, pid, payload):
        project = self.get_owned(user, pid)
        assert project.last_index_version is not None
        conn = self.db.connection()
        conn.info["r02_publish_replacement"] = True
        try:
            return real_update(self, user, pid, payload)
        finally:
            conn.info.pop("r02_publish_replacement", None)

    def before_write(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().lower()
        if sql.startswith("insert into diagrams"):
            # 发布守卫已取得锁；只等待 B 开始写，随后 A 可以提交释放锁。
            publish_locked.set()
            assert replacement_attempted.wait(10)
        elif conn.info.get("r02_publish_replacement") and sql.startswith("update"):
            replacement_attempted.set()

    monkeypatch.setattr(ProjectService, "update_project", observed_update)
    event.listen(test_database["engine"], "before_cursor_execute", before_write)
    a = _start(lambda: _analyze(client, auth_header, project_id))
    b = None
    try:
        assert publish_locked.wait(10)
        b = _start(lambda: _replace(client, auth_header, project_id, uploads[1]))
        generated = _finish(a)
        _finish(b)
    finally:
        replacement_attempted.set()
        a[0].join(15)
        if b:
            b[0].join(15)
        event.remove(test_database["engine"], "before_cursor_execute", before_write)
    assert generated.status_code == 200, generated.text
    assert generated.json()["data"]["status"] == "success"
    with test_database["session_factory"]() as db:
        project = db.get(Project, project_id)
        assert (project.repository.upload_id, project.status, project.last_index_version, project.file_count) == (uploads[1], "created", None, 0)
        assert db.get(Diagram, generated.json()["data"]["diagram_id"]).is_outdated is True
    assert _analyze(client, auth_header, project_id).status_code == 409


def test_b_replaces_and_parses_before_a_guard_preserves_complete_b_index(client, auth_header, test_database):
    project_id, uploads = _setup(client, auth_header)
    a_before_guard, release_a = Event(), Event()

    def before_guard(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().lower()
        if sql.startswith("update projects") and "exists" in sql and "parsing" in parameters and not a_before_guard.is_set():
            a_before_guard.set()
            # 首次条件写入尚未执行，B 能完整提交。
            assert release_a.wait(10)

    event.listen(test_database["engine"], "before_cursor_execute", before_guard)
    a = _start(lambda: _parse(client, auth_header, project_id))
    try:
        assert a_before_guard.wait(10)
        _replace(client, auth_header, project_id, uploads[1])
        assert _parse(client, auth_header, project_id).json()["data"]["status"] == "success"
        with test_database["session_factory"]() as db:
            new_index = _assert_new_index(db, project_id, uploads[1], "new_entry")
        release_a.set()
        rejected = _finish(a)
    finally:
        release_a.set()
        a[0].join(15)
        event.remove(test_database["engine"], "before_cursor_execute", before_guard)
    assert rejected.json()["data"]["status"] == "failed"
    with test_database["session_factory"]() as db:
        assert _assert_new_index(db, project_id, uploads[1], "new_entry") == new_index
    assert _analyze(client, auth_header, project_id).status_code == 200


def test_old_failure_cannot_take_over_new_running_operation_with_same_source_and_revision(client, auth_header, test_database, monkeypatch):
    project_id, uploads = _setup(client, auth_header)
    assert _parse(client, auth_header, project_id).json()["data"]["status"] == "success"
    rolled_back, finish_old, new_before_guard, release_new, intercepted = (Event() for _ in range(5))
    real_parse, real_failed = index_module.parse_project, IndexService._persist_failed

    def fail_once(*args, **kwargs):
        if not intercepted.is_set():
            intercepted.set()
            raise RuntimeError("old operation fails")
        return real_parse(*args, **kwargs)

    def pause_old(self, *args, **kwargs):
        self.db.rollback()
        rolled_back.set()
        assert finish_old.wait(10)
        return real_failed(self, *args, **kwargs)

    def pause_new_guard(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().lower()
        if sql.startswith("update projects") and "exists" in sql and parameters[0] == "parsing":
            new_before_guard.set()
            assert release_new.wait(10)

    monkeypatch.setattr(index_module, "parse_project", fail_once)
    monkeypatch.setattr(IndexService, "_persist_failed", pause_old)
    a = _start(lambda: _parse(client, auth_header, project_id))
    b = None
    try:
        assert rolled_back.wait(10)
        with test_database["session_factory"]() as db:
            old_revision = db.get(Project, project_id).last_index_version
        event.listen(test_database["engine"], "before_cursor_execute", pause_new_guard)
        b = _start(lambda: _parse(client, auth_header, project_id))
        assert new_before_guard.wait(10)
        finish_old.set()
        assert _finish(a).json()["data"]["status"] == "failed"
        with test_database["session_factory"]() as db:
            project = db.get(Project, project_id)
            assert project.status == "parsing"
            assert project.last_index_version == old_revision
            assert project.repository.upload_id == uploads[0]
        release_new.set()
        assert _finish(b).json()["data"]["status"] == "success"
    finally:
        finish_old.set()
        release_new.set()
        a[0].join(15)
        if b:
            b[0].join(15)
        if event.contains(test_database["engine"], "before_cursor_execute", pause_new_guard):
            event.remove(test_database["engine"], "before_cursor_execute", pause_new_guard)
    with test_database["session_factory"]() as db:
        revision, _ = _assert_new_index(db, project_id, uploads[0], "old_entry")
        assert revision == old_revision  # C12: operation identity is not content identity.
    assert _analyze(client, auth_header, project_id).status_code == 200


@pytest.mark.parametrize("operation", ["parse", "sync"])
def test_missing_zip_failure_is_queryable_and_keeps_old_index(client, auth_header, test_database, operation):
    project_id, uploads = _setup(client, auth_header)
    assert _parse(client, auth_header, project_id).json()["data"]["status"] == "success"
    factory = test_database["session_factory"]
    with factory() as db:
        rows = _index_rows(db, project_id)
        revision = db.get(Project, project_id).last_index_version
        path = test_database["storage_path"] / db.get(Upload, uploads[0]).object_key
        assert path.resolve().is_relative_to(test_database["storage_path"].resolve())
        path.unlink()
    failed = client.post(f"/api/projects/{project_id}/{operation}", headers=auth_header, json={"mode": "sync"})
    assert failed.status_code == 200, failed.text
    assert failed.json()["data"]["status"] == "failed"
    tracked = client.get(f"/api/tasks/{failed.json()['data']['task_id']}", headers=auth_header)
    assert tracked.status_code == 200, tracked.text
    assert tracked.json()["data"]["status"] == "failed"
    with factory() as db:
        project = db.get(Project, project_id)
        assert project.status == "failed"
        assert project.last_index_version == revision
        assert _index_rows(db, project_id) == rows
    assert _analyze(client, auth_header, project_id).status_code == 409


def test_replacement_and_audit_failure_roll_back_as_one_transaction(client, auth_header, test_database, monkeypatch):
    from fastapi.testclient import TestClient

    project_id, uploads = _setup(client, auth_header)
    assert _parse(client, auth_header, project_id).json()["data"]["status"] == "success"
    generated = _analyze(client, auth_header, project_id)
    assert generated.status_code == 200, generated.text
    diagram_id = generated.json()["data"]["diagram_id"]
    with test_database["session_factory"]() as db:
        revision = db.get(Project, project_id).last_index_version
        rows = _index_rows(db, project_id)

    def fail_audit(*args, **kwargs):
        raise RuntimeError("controlled audit failure")

    monkeypatch.setattr(AuditService, "record", fail_audit)
    with TestClient(client.app, raise_server_exceptions=False) as error_client:
        response = error_client.patch(f"/api/projects/{project_id}", headers=auth_header, json={"upload_id": uploads[1]})
    assert response.status_code == 500, response.text
    with test_database["session_factory"]() as db:
        assert _assert_new_index(db, project_id, uploads[0], "old_entry") == (revision, rows)
        assert db.get(Diagram, diagram_id).is_outdated is False
        assert db.scalar(select(AuditLog).where(AuditLog.action == "project.update")) is None
