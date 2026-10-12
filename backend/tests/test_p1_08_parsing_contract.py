from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.exceptions import AppException
from app.core.config import get_settings
from app.agents.orchestrator import AgentOrchestrator
from app.core.config import Settings
from app.models.analysis_task import AnalysisTask
from app.models.code_chunk import CodeChunk
from app.models.project import Project
from app.models.repository import Repository
from app.models.source_file import SourceFile
from app.models.symbol import Symbol
from app.models.upload import Upload
from app.models.user import User
from app.parsing.file_scanner import scan_zip_inventory
from app.parsing.chunker import chunk_and_save
from app.parsing.tree_parser import parse_source
from app.services.index_service import IndexService


def _project_with_zip(db, demo_zip: dict) -> Project:
    now = datetime.now(timezone.utc)
    user = User(
        email="p1-08@example.com",
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
        name="p1-08-project",
        source_type="zip",
        status="created",
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.flush()
    db.add(Repository(project_id=project.id, upload_id=upload.id, created_at=now))
    db.flush()
    return project


def test_parse_stats_file_count_result_and_diagnostics(db_session, demo_zip):
    project = _project_with_zip(db_session, demo_zip)
    task = AnalysisTask(
        project_id=project.id,
        user_id=project.owner_id,
        task_type="parse",
        status="pending",
        progress=0,
    )
    db_session.add(task)
    db_session.flush()

    parsed = IndexService(db_session).parse_full(project, task)

    assert parsed.status == "success"
    assert project.file_count == 3
    assert parsed.result_json["source_files"] == 3
    assert parsed.result_json["python_files"] == 2
    assert parsed.result_json["symbols"] >= 2
    assert parsed.result_json["chunks"] > parsed.result_json["symbols"]
    assert parsed.result_json["dependencies"] >= 1
    assert {item["relative_path"] for item in parsed.result_json["diagnostics"]} == {
        "demo.py",
        "helpers.py",
        "README.md",
    }
    assert "文件 3 个" in parsed.message
    assert "stats" not in parsed.result_json

    source_files = {
        item.relative_path: item
        for item in db_session.query(SourceFile).filter_by(project_id=project.id).all()
    }
    assert source_files["README.md"].line_count == 1
    assert source_files["demo.py"].line_count == 5

    python_file_ids = {item.id for item in source_files.values() if item.language == "python"}
    module_chunks = (
        db_session.query(CodeChunk)
        .filter(CodeChunk.project_id == project.id, CodeChunk.chunk_type == "module")
        .all()
    )
    assert {chunk.file_id for chunk in module_chunks} == python_file_ids
    assert all(chunk.start_line == 1 and chunk.end_line == source_files[next(
        path for path, item in source_files.items() if item.id == chunk.file_id
    )].line_count for chunk in module_chunks)
    for symbol in db_session.query(Symbol).filter_by(project_id=project.id).all():
        assert db_session.query(CodeChunk).filter_by(
            project_id=project.id,
            file_id=symbol.file_id,
            chunk_type=symbol.kind,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
        ).first() is not None


def test_scanner_limits_actual_cumulative_member_reads(tmp_path: Path, monkeypatch):
    archive_path = tmp_path / "scan-limit.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("one.py", "12345")
        archive.writestr("two.py", "67890")

    settings = get_settings()
    monkeypatch.setattr(settings, "max_zip_member_uncompressed_size_mb", 1)
    monkeypatch.setattr(settings, "max_zip_total_uncompressed_size_mb", 0)

    with pytest.raises(AppException, match="实际读取总大小"):
        scan_zip_inventory(archive_path)



def test_module_chunk_preserves_tail_when_function_starts_at_first_line(db_session, demo_zip):
    project = _project_with_zip(db_session, demo_zip)
    code = 'def first():\n    return 1\n\nLIMIT = 10\nif __name__ == "__main__":\n    first()\n'
    source_file = SourceFile(
        project_id=project.id,
        relative_path="first.py",
        language="python",
        file_hash="module-tail-test",
        size_bytes=len(code.encode("utf-8")),
        line_count=len(code.splitlines()),
        parse_status="parsed",
    )
    db_session.add(source_file)
    db_session.flush()
    symbols = parse_source(code)
    chunk_and_save(db_session, project.id, source_file.id, code, symbols)
    chunks = db_session.query(CodeChunk).filter_by(file_id=source_file.id).all()

    assert symbols[0].start_line == 1
    assert any(chunk.chunk_type == "module" and chunk.content == code.rstrip() for chunk in chunks)
    assert AgentOrchestrator(Settings(llm_enabled="off"))._merge_file_chunks(chunks) == code.rstrip()


def test_decorated_route_module_evidence_reaches_local_provider(db_session, demo_zip, monkeypatch):
    from app.agents import llm_provider

    project = _project_with_zip(db_session, demo_zip)
    code = "\n".join(
        (
            "from fastapi import FastAPI",
            "LIMIT = 10",
            "app = FastAPI()",
            "",
            '@app.post("/checkout")',
            "def checkout():",
            '    return {"limit": LIMIT}',
            "",
            'if __name__ == "__main__":',
            "    checkout()",
        )
    )
    source_file = SourceFile(
        project_id=project.id,
        relative_path="routes.py",
        language="python",
        file_hash="route-context-test",
        size_bytes=len(code.encode("utf-8")),
        line_count=len(code.splitlines()),
        parse_status="parsed",
    )
    db_session.add(source_file)
    db_session.flush()
    symbols = parse_source(code)
    route = next(symbol for symbol in symbols if symbol.name == "checkout")
    assert route.start_line == 5
    for symbol in symbols:
        db_session.add(
            Symbol(
                project_id=project.id,
                file_id=source_file.id,
                name=symbol.name,
                kind=symbol.kind,
                qualified_name=symbol.qualified_name,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                signature=symbol.signature,
            )
        )
    chunk_and_save(db_session, project.id, source_file.id, code, symbols)
    captured = {}

    class LocalProvider:
        def __init__(self, model, settings):
            self.model = model

        def chat(self, system_prompt, user_prompt):
            captured["user_prompt"] = user_prompt
            return "\n".join(("flowchart TD", "A[checkout] --> B[return]"))

    monkeypatch.setattr(llm_provider, "LLMProvider", LocalProvider)
    result = AgentOrchestrator(Settings(llm_enabled="model", llm_api_key="local-test-key")).run_analysis(
        "checkout-service",
        "生成结账流程",
        "flowchart",
        db=db_session,
        project_id=project.id,
    )

    assert result.quality_status == "unverified"
    for evidence in (
        "from fastapi import FastAPI",
        "LIMIT = 10",
        "app = FastAPI()",
        '@app.post("/checkout")',
        'if __name__ == "__main__":',
    ):
        assert evidence in captured["user_prompt"]



def test_api_upload_parse_analysis_reaches_local_provider_with_snapshot_evidence(
    client, demo_zip, auth_header, monkeypatch
):
    from app.core.config import get_settings
    from app.agents import llm_provider

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_enabled", "model")
    monkeypatch.setattr(settings, "llm_api_key", "local-test-key")
    calls = []

    class LocalProvider:
        def __init__(self, model, settings):
            self.model = model

        def chat(self, system_prompt, user_prompt):
            calls.append(user_prompt)
            if "sequence" in user_prompt.lower():
                return "sequenceDiagram\n    participant A\n    A->>A: main"
            if "state" in user_prompt.lower():
                return "stateDiagram-v2\n    [*] --> Ready"
            if "architecture" in user_prompt.lower():
                return "classDiagram\n    class Main"
            return "flowchart TD\n    A[main] --> B[greet]"

    monkeypatch.setattr(llm_provider, "LLMProvider", LocalProvider)
    upload = client.post(
        "/api/uploads",
        headers=auth_header,
        files={"file": ("source.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    created = client.post(
        "/api/projects",
        headers=auth_header,
        json={
            "name": "api-snapshot-evidence",
            "source_type": "zip",
            "upload_id": upload.json()["data"]["upload_id"],
        },
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["data"]["project"]["id"]
    parsed = client.post(
        f"/api/projects/{project_id}/parse",
        headers=auth_header,
        json={"mode": "sync"},
    )
    assert parsed.status_code == 200, parsed.text
    for diagram_type in ("flowchart", "sequence", "state", "architecture"):
        response = client.post(
            f"/api/projects/{project_id}/analysis",
            headers=auth_header,
            json={"prompt": "根据源码生成图", "diagram_type": diagram_type},
        )
        assert response.status_code == 200, response.text
        diagram_id = response.json()["data"]["diagram_id"]
        assert diagram_id is not None
        if diagram_type == "flowchart":
            diagram = client.get(f"/api/diagrams/{diagram_id}", headers=auth_header)
            assert diagram.status_code == 200, diagram.text
            mapping = diagram.json()["data"]["node_mapping_json"] or {}
            evidence = [
                value for value in mapping.values()
                if isinstance(value, dict) and value.get("file_path") == "demo.py"
            ]
            assert evidence
            assert any(value.get("file_hash") and value.get("symbol_id") for value in evidence)
            assert any(value.get("start_line") and value.get("end_line") for value in evidence)
    assert len(calls) == 4
    assert all(
        "demo.py" in prompt and "def main" in prompt and "from helpers import greet" in prompt
        for prompt in calls
    )


