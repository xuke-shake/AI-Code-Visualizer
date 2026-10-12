from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.core.database import engine
from app.models.agent_run import AgentRun
from app.models.analysis_task import AnalysisTask
from app.models.code_chunk import CodeChunk
from app.models.dependency import Dependency
from app.models.diagram import Diagram
from app.models.project import Project
from app.models.repository import Repository
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.upload import Upload
from app.models.user import User
from app.services.project_service import ProjectService


def _make_graph(db, storage: Path, *, shared_upload: Upload | None = None):
    now = datetime.now(timezone.utc)
    user = User(
        email=f"cleanup-{id(storage)}-{now.timestamp()}@example.com",
        password_hash="not-used",
        role="user",
        status="normal",
        created_at=now,
    )
    db.add(user)
    db.flush()
    upload = shared_upload or Upload(
        owner_id=user.id,
        object_key=f"uploads/{user.id}/source.zip",
        original_filename="source.zip",
        size_bytes=3,
        file_count=1,
        accepted_source_files=1,
        validation_status="validated",
        created_at=now,
    )
    if shared_upload is None:
        db.add(upload)
        db.flush()
    project = Project(
        owner_id=user.id,
        name="cleanup",
        source_type="zip",
        status="ready",
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.flush()
    repository = Repository(
        project_id=project.id,
        upload_id=upload.id,
        local_path=f"projects/{project.id}",
        created_at=now,
    )
    db.add(repository)
    source_file = SourceFile(
        project_id=project.id,
        relative_path="main.py",
        language="python",
        file_hash="a" * 64,
        size_bytes=3,
        line_count=1,
        parse_status="parsed",
    )
    db.add(source_file)
    db.flush()
    symbol = Symbol(
        project_id=project.id,
        file_id=source_file.id,
        name="main",
        kind="function",
        start_line=1,
        end_line=1,
    )
    db.add(symbol)
    chunk = CodeChunk(
        project_id=project.id,
        file_id=source_file.id,
        chunk_type="function",
        symbol_name="main",
        start_line=1,
        end_line=1,
        content="def main(): pass",
    )
    db.add(chunk)
    db.flush()
    db.add(
        Dependency(
            project_id=project.id,
            source_file_id=source_file.id,
            target_file_id=source_file.id,
            relation_type="imports",
        )
    )
    task = AnalysisTask(
        project_id=project.id,
        user_id=user.id,
        task_type="diagram",
        status="success",
        progress=100,
        created_at=now,
        finished_at=now,
    )
    db.add(task)
    db.flush()
    db.add(AgentRun(task_id=task.id, agent_name="test", status="success"))
    db.add(
        Diagram(
            project_id=project.id,
            creator_id=user.id,
            title="cleanup",
            diagram_type="flowchart",
            mermaid_code="flowchart TD\nA-->B",
        )
    )
    db.flush()
    return user, project, upload


def _counts(db, project_id: int) -> dict[str, int]:
    return {
        "repositories": db.query(Repository).filter_by(project_id=project_id).count(),
        "source_files": db.query(SourceFile).filter_by(project_id=project_id).count(),
        "symbols": db.query(Symbol).filter_by(project_id=project_id).count(),
        "chunks": db.query(CodeChunk).filter_by(project_id=project_id).count(),
        "dependencies": db.query(Dependency).filter_by(project_id=project_id).count(),
        "tasks": db.query(AnalysisTask).filter_by(project_id=project_id).count(),
        "diagrams": db.query(Diagram).filter_by(project_id=project_id).count(),
    }


def test_sqlite_foreign_keys_are_enabled():
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_delete_project_removes_all_index_records_and_orphan_upload(db_session, test_database):
    _, project, upload = _make_graph(db_session, test_database["storage_path"])
    project_id = project.id
    upload_id = upload.id
    upload_path = test_database["storage_path"] / upload.object_key
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(b"zip")
    project_path = test_database["storage_path"] / "projects" / str(project.id)
    project_path.mkdir(parents=True)
    (project_path / "checkout.txt").write_text("private", encoding="utf-8")
    db_session.commit()

    ProjectService(db_session).delete_project(
        db_session.get(User, project.owner_id), project.id
    )

    assert db_session.get(Project, project_id) is None
    assert _counts(db_session, project_id) == {
        "repositories": 0,
        "source_files": 0,
        "symbols": 0,
        "chunks": 0,
        "dependencies": 0,
        "tasks": 0,
        "diagrams": 0,
    }
    assert db_session.get(Upload, upload_id) is None
    assert not upload_path.exists()
    assert not project_path.exists()


def test_shared_upload_is_preserved_until_last_project_is_deleted(db_session, test_database):
    user, first, upload = _make_graph(db_session, test_database["storage_path"])
    second = Project(
        owner_id=user.id,
        name="second",
        source_type="zip",
        status="ready",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(second)
    db_session.flush()
    db_session.add(Repository(project_id=second.id, upload_id=upload.id, created_at=datetime.now(timezone.utc)))
    db_session.commit()
    upload_path = test_database["storage_path"] / upload.object_key
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(b"zip")

    ProjectService(db_session).delete_project(user, first.id)
    assert db_session.get(Upload, upload.id) is not None
    assert upload_path.exists()

    ProjectService(db_session).delete_project(user, second.id)
    assert db_session.get(Upload, upload.id) is None
    assert not upload_path.exists()


def test_outside_database_confirmed_path_is_not_deleted(db_session, test_database, tmp_path):
    user, project, upload = _make_graph(db_session, test_database["storage_path"])
    outside = tmp_path / "outside-project"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    project.repository.local_path = str(outside)
    db_session.commit()

    ProjectService(db_session).delete_project(user, project.id)

    assert (outside / "keep.txt").exists()
    assert db_session.get(Upload, upload.id) is None
