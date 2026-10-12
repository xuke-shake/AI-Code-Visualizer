from __future__ import annotations

from datetime import datetime, timezone
from zipfile import ZipFile

import pytest

from app.models.analysis_task import AnalysisTask
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.repository import Repository
from app.models.source_file import SourceFile
from app.models.upload import Upload
from app.models.user import User
from app.services.index_service import IndexService


def _project_with_zip(db, demo_zip: dict) -> tuple[Project, Upload]:
    now = datetime.now(timezone.utc)
    user = User(
        email="p1-09@example.com",
        password_hash="not-used",
        role="user",
        status="normal",
        created_at=now,
    )
    db.add(user)
    db.flush()
    upload = Upload(
        owner_id=user.id,
        object_key=str(demo_zip["object_key"]),
        original_filename="demo.zip",
        size_bytes=demo_zip["path"].stat().st_size,
        file_count=3,
        accepted_source_files=3,
        validation_status="validated",
        created_at=now,
    )
    db.add(upload)
    db.flush()
    project = Project(
        owner_id=user.id,
        name="p1-09-project",
        source_type="zip",
        status="created",
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.flush()
    db.add(Repository(project_id=project.id, upload_id=upload.id, created_at=now))
    db.flush()
    return project, upload


def _task(db, project: Project, task_type: str) -> AnalysisTask:
    task = AnalysisTask(
        project_id=project.id,
        user_id=project.owner_id,
        task_type=task_type,
        status="pending",
        progress=0,
    )
    db.add(task)
    db.flush()
    return task


def _write_zip(path, entries: dict[str, str]) -> None:
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_sync_deletes_files_reuses_modified_id_and_marks_diagram(db_session, demo_zip):
    project, _ = _project_with_zip(db_session, demo_zip)
    IndexService(db_session).parse_full(project, _task(db_session, project, "parse"))
    original = {
        item.relative_path: item
        for item in db_session.query(SourceFile).filter_by(project_id=project.id).all()
    }
    diagram = Diagram(
        project_id=project.id,
        creator_id=project.owner_id,
        title="旧图",
        diagram_type="flowchart",
        mermaid_code="flowchart TD\nA-->B",
        node_mapping_json={
            "demo": {"file_id": original["demo.py"].id, "symbol_id": 999999},
        },
    )
    db_session.add(diagram)
    db_session.flush()

    _write_zip(
        demo_zip["path"],
        {
            "demo.py": "from helpers import greet\n\ndef main(name='changed'):\n    return greet(name)\n",
            "helpers.py": "def greet(name):\n    return f'Hi {name}'\n",
            "new.py": "def added():\n    return True\n",
        },
    )
    synced = IndexService(db_session).sync_incremental(project, _task(db_session, project, "sync"))

    assert synced.status == "success"
    assert synced.result_json["added"] == ["new.py"]
    assert synced.result_json["modified"] == ["demo.py", "helpers.py"]
    assert synced.result_json["deleted"] == ["README.md"]
    assert synced.result_json["outdated_diagrams"] == 1
    assert db_session.get(Diagram, diagram.id).is_outdated is True

    current = {
        item.relative_path: item
        for item in db_session.query(SourceFile).filter_by(project_id=project.id).all()
    }
    assert "README.md" not in current
    assert current["demo.py"].id == original["demo.py"].id
    assert current["helpers.py"].id == original["helpers.py"].id
    assert current["new.py"].id not in {
        original["demo.py"].id,
        original["helpers.py"].id,
    }


def test_sync_failure_is_persisted(monkeypatch, db_session, demo_zip):
    project, _ = _project_with_zip(db_session, demo_zip)
    IndexService(db_session).parse_full(project, _task(db_session, project, "parse"))

    def explode(_path):
        raise RuntimeError("scanner failed")

    monkeypatch.setattr("app.services.index_service.scan_zip_inventory", explode)
    failed = IndexService(db_session).sync_incremental(project, _task(db_session, project, "sync"))

    assert failed.status == "failed"
    assert failed.finished_at is not None
    assert db_session.get(Project, project.id).status == "failed"


def test_full_parse_marks_existing_diagrams_outdated(db_session, demo_zip):
    project, _ = _project_with_zip(db_session, demo_zip)
    diagram = Diagram(
        project_id=project.id,
        creator_id=project.owner_id,
        title="旧图",
        diagram_type="flowchart",
        mermaid_code="flowchart TD\nA-->B",
        is_outdated=False,
    )
    db_session.add(diagram)
    db_session.flush()
    IndexService(db_session).parse_full(project, _task(db_session, project, "parse"))
    assert db_session.get(Diagram, diagram.id).is_outdated is True



def test_full_parse_failure_rolls_back_old_index_and_diagram_state(db_session, demo_zip, monkeypatch):
    project, _ = _project_with_zip(db_session, demo_zip)
    IndexService(db_session).parse_full(project, _task(db_session, project, "parse"))
    old_revision = project.last_index_version
    old_diagram = Diagram(
        project_id=project.id,
        creator_id=project.owner_id,
        title="旧图",
        diagram_type="flowchart",
        mermaid_code="flowchart TD\nA-->B",
        is_outdated=False,
    )
    db_session.add(old_diagram)
    db_session.commit()

    def explode(*args, **kwargs):
        raise RuntimeError("parse failure")

    monkeypatch.setattr("app.services.index_service.parse_project", explode)
    failed = IndexService(db_session).parse_full(project, _task(db_session, project, "parse"))
    assert failed.status == "failed"
    db_session.expire_all()
    current = db_session.get(Project, project.id)
    restored = db_session.get(Diagram, old_diagram.id)
    assert current.last_index_version == old_revision
    assert restored.is_outdated is False



def test_full_parse_rejects_stale_upload_snapshot_after_second_session_replaces_source(
    db_session, demo_zip, test_database
):
    project, original = _project_with_zip(db_session, demo_zip)
    db_session.commit()
    stale_project = db_session.get(Project, project.id)
    assert stale_project.repository.upload_id == original.id

    replacement_path = test_database["storage_path"] / "uploads" / "1" / "replacement.zip"
    replacement_path.write_bytes(demo_zip["path"].read_bytes())
    with test_database["session_factory"]() as concurrent_db:
        replacement = Upload(
            owner_id=project.owner_id,
            object_key="uploads/1/replacement.zip",
            original_filename="replacement.zip",
            size_bytes=replacement_path.stat().st_size,
            file_count=3,
            accepted_source_files=3,
            validation_status="validated",
            created_at=datetime.now(timezone.utc),
        )
        concurrent_db.add(replacement)
        concurrent_db.flush()
        replacement_id = replacement.id
        repository = concurrent_db.query(Repository).filter_by(project_id=project.id).one()
        repository.upload_id = replacement.id
        concurrent_db.commit()

    failed = IndexService(db_session).parse_full(stale_project, _task(db_session, stale_project, "parse"))
    assert failed.status == "failed"
    with test_database["session_factory"]() as check_db:
        current = check_db.get(Project, project.id)
        assert current.repository.upload_id == replacement_id
        assert current.last_index_version is None



def test_file_and_symbol_ids_are_not_compared_as_same_namespace():
    assert IndexService._json_refers_to({"symbol_id": 12}, {12}) is False
    assert IndexService._json_refers_to({"nested": {"file_id": 12}}, {12}) is True


def test_changes_endpoint_returns_latest_sync_result(client, demo_zip, auth_header):
    upload = client.post(
        "/api/uploads",
        headers=auth_header,
        files={"file": ("demo.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    project = client.post(
        "/api/projects",
        headers=auth_header,
        json={
            "name": "changes-project",
            "source_type": "zip",
            "upload_id": upload.json()["data"]["upload_id"],
        },
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["data"]["project"]["id"]
    parsed = client.post(f"/api/projects/{project_id}/parse", headers=auth_header, json={"mode": "sync"})
    assert parsed.status_code == 200, parsed.text

    synced = client.post(f"/api/projects/{project_id}/sync", headers=auth_header, json={})
    assert synced.status_code == 200, synced.text
    changes = client.get(f"/api/projects/{project_id}/changes", headers=auth_header)
    assert changes.status_code == 200, changes.text
    data = changes.json()["data"]
    assert data["task_id"] == synced.json()["data"]["task_id"]
    assert data["status"] == "success"
    assert data["added"] == []
    assert data["modified"] == []
    assert data["deleted"] == []


def test_refresh_endpoint_does_not_clear_outdated_flag(client, demo_zip, auth_header, test_database):
    upload = client.post(
        "/api/uploads",
        headers=auth_header,
        files={"file": ("demo.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    project = client.post(
        "/api/projects",
        headers=auth_header,
        json={
            "name": "refresh-project",
            "source_type": "zip",
            "upload_id": upload.json()["data"]["upload_id"],
        },
    )
    project_id = project.json()["data"]["project"]["id"]
    parsed = client.post(f"/api/projects/{project_id}/parse", headers=auth_header, json={"mode": "sync"})
    assert parsed.status_code == 200, parsed.text
    created = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=auth_header,
        json={"prompt": "生成流程图", "diagram_type": "flowchart"},
    )
    assert created.status_code == 200, created.text
    diagram_id = created.json()["data"]["diagram_id"]

    db = test_database["session_factory"]()
    try:
        diagram = db.get(Diagram, diagram_id)
        diagram.is_outdated = True
        db.commit()
    finally:
        db.close()

    refreshed = client.post(f"/api/diagrams/{diagram_id}/refresh", headers=auth_header)
    assert refreshed.status_code == 409, refreshed.text
    assert "过期" in refreshed.json()["message"]
