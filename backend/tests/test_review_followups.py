from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from app.agents.orchestrator import AgentOrchestrator
from app.core.config import Settings, get_settings
from app.models.analysis_task import AnalysisTask
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.repository import Repository
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.user import User
from app.services.diagram_service import DiagramService
from app.services.index_service import IndexService
from app.services.project_service import ProjectService
from app.schemas.diagram import DiagramUpdate


def _user(db, email: str = "review@example.com") -> User:
    user = User(email=email, password_hash="unused", role="user", status="normal")
    db.add(user)
    db.flush()
    return user


def _task(db, project: Project, kind: str = "parse") -> AnalysisTask:
    task = AnalysisTask(
        project_id=project.id,
        user_id=project.owner_id,
        task_type=kind,
        status="pending",
        progress=0,
    )
    db.add(task)
    db.flush()
    return task


def _project_with_legacy_zip(db, demo_zip: dict) -> Project:
    user = _user(db)
    project = Project(owner_id=user.id, name="legacy", source_type="zip", status="created")
    db.add(project)
    db.flush()
    db.add(
        Repository(
            project_id=project.id,
            zip_object_key=str(demo_zip["object_key"]),
            created_at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    return project


def _write_zip(path: Path, entries: dict[str, str]) -> None:
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_legacy_zip_is_bound_and_parse_sync_continue(db_session, demo_zip):
    project = _project_with_legacy_zip(db_session, demo_zip)
    parsed = IndexService(db_session).parse_full(project, _task(db_session, project))
    db_session.refresh(project)
    assert parsed.status == "success"
    assert project.repository.upload_id is not None
    assert project.repository.upload.object_key != demo_zip["object_key"]
    assert project.repository.upload.object_key.startswith(f"uploads/{project.owner_id}/")
    assert (get_settings().storage_path / project.repository.upload.object_key).is_file()

    synced = IndexService(db_session).sync_incremental(project, _task(db_session, project, "sync"))
    assert synced.status == "success"


def test_legacy_zip_outside_or_symlink_is_rejected(db_session, demo_zip, test_database, monkeypatch):
    project = _project_with_legacy_zip(db_session, demo_zip)
    project.repository.zip_object_key = "../outside.zip"
    failed = IndexService(db_session).parse_full(project, _task(db_session, project))
    assert failed.status == "failed"


def test_mermaid_update_clears_mapping_but_title_update_keeps_it(db_session):
    user = _user(db_session, "diagram-review@example.com")
    project = Project(owner_id=user.id, name="diagram", source_type="zip", status="ready")
    db_session.add(project)
    db_session.flush()
    diagram = Diagram(
        project_id=project.id,
        creator_id=user.id,
        title="old",
        diagram_type="flowchart",
        mermaid_code="flowchart TD\nA-->B",
        node_mapping_json={"A": {"file_path": "a.py"}},
    )
    db_session.add(diagram)
    db_session.commit()

    service = DiagramService(db_session)
    service.update_diagram(user, diagram.id, DiagramUpdate(title="new"))
    assert db_session.get(Diagram, diagram.id).node_mapping_json == {"A": {"file_path": "a.py"}}
    service.update_diagram(user, diagram.id, DiagramUpdate(mermaid_code="flowchart TD\nA-->C"))
    updated = db_session.get(Diagram, diagram.id)
    assert updated.node_mapping_json is None


def test_added_and_file_path_mapping_changes_mark_all_old_diagrams_outdated(db_session, demo_zip):
    project = _project_with_legacy_zip(db_session, demo_zip)
    IndexService(db_session).parse_full(project, _task(db_session, project))
    diagrams = [
        Diagram(
            project_id=project.id,
            creator_id=project.owner_id,
            title=f"d{i}",
            diagram_type="flowchart",
            mermaid_code="flowchart TD\nA-->B",
            is_outdated=False,
            node_mapping_json={"A": {"file_path": "old.py"}} if i else None,
        )
        for i in range(2)
    ]
    db_session.add_all(diagrams)
    db_session.commit()

    migrated_zip = get_settings().storage_path / project.repository.upload.object_key
    _write_zip(migrated_zip, {"demo.py": "def main():\n    return 2\n", "helpers.py": "def greet():\n    return 'x'\n", "new.py": "def added():\n    return True\n"})
    synced = IndexService(db_session).sync_incremental(project, _task(db_session, project, "sync"))
    assert synced.result_json["outdated_diagrams"] == 2
    assert all(item.is_outdated for item in db_session.query(Diagram).filter_by(project_id=project.id))


def test_no_file_change_does_not_mark_diagram(db_session, demo_zip):
    project = _project_with_legacy_zip(db_session, demo_zip)
    IndexService(db_session).parse_full(project, _task(db_session, project))
    diagram = Diagram(
        project_id=project.id,
        creator_id=project.owner_id,
        title="stable",
        diagram_type="flowchart",
        mermaid_code="flowchart TD\nA-->B",
        is_outdated=False,
    )
    db_session.add(diagram)
    db_session.commit()
    synced = IndexService(db_session).sync_incremental(project, _task(db_session, project, "sync"))
    assert synced.result_json["outdated_diagrams"] == 0
    assert db_session.get(Diagram, diagram.id).is_outdated is False


def test_git_create_delete_cleans_project_and_snapshot(client, auth_header, monkeypatch, test_database):
    def fake_clone(self, repo_url, branch, project_id):
        path = self.project_path(project_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "main.py").write_text("def main():\n    return True\n", encoding="utf-8")
        return path

    monkeypatch.setattr("app.api.projects.GitService.clone_for_project", fake_clone)
    created = client.post(
        "/api/projects",
        headers=auth_header,
        json={"name": "git-cleanup", "source_type": "git", "repo_url": "https://github.com/acme/demo"},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["data"]["project"]["id"]
    root = test_database["storage_path"]
    project_dir = root / "projects" / str(project_id)
    snapshot_dir = root / "snapshots" / str(project_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "snapshot-test.zip").write_bytes(b"snapshot")
    assert project_dir.is_dir()
    deleted = client.delete(f"/api/projects/{project_id}", headers=auth_header)
    assert deleted.status_code == 200, deleted.text
    assert not project_dir.exists()
    assert not snapshot_dir.exists()


def test_llm_output_is_unverified_without_business_validation(monkeypatch, tmp_path):
    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "main.py").write_text("def main():\n    return True\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT_PATH", str(source_root))
    orchestrator = AgentOrchestrator(Settings(llm_enabled="model", llm_api_key="test-key"))
    monkeypatch.setattr(
        orchestrator,
        "_try_llm_mermaid",
        lambda **kwargs: ("flowchart TD\nA-->B", None),
    )
    result = orchestrator.run_analysis("repo", "生成图", "flowchart")
    assert result.quality_status == "unverified"
    assert "预检查" in result.reason
