from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from app.models.analysis_task import AnalysisTask
from app.models.symbol import Symbol


def _source_zip(filename: str, source: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(filename, source)
    return buffer.getvalue()


def _task_count(test_database, project_id: int) -> int:
    with test_database["session_factory"]() as db:
        return db.query(AnalysisTask).filter_by(project_id=project_id).count()

def _upload(client, headers, demo_zip):
    return client.post(
        "/api/uploads",
        headers=headers,
        files={"file": ("demo.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )


def test_upload_returns_owned_id_and_uses_distinct_private_keys(client, demo_zip, auth_header, test_database):
    first = _upload(client, auth_header, demo_zip)
    second = _upload(client, auth_header, demo_zip)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert first_data["upload_id"] != second_data["upload_id"]
    assert first_data["validation_status"] == "validated"
    assert "object_key" not in first_data

    # 每次上传都应写入独立对象，不能因原始文件名相同而覆盖。
    stored = list((test_database["storage_path"] / "uploads" / "1").glob("*.zip"))
    assert len(stored) >= 2
    assert len({item.name for item in stored}) == len(stored)


def test_project_accepts_only_owned_validated_upload_id(client, demo_zip, auth_header):
    upload = _upload(client, auth_header, demo_zip)
    upload_id = upload.json()["data"]["upload_id"]

    created = client.post(
        "/api/projects",
        headers=auth_header,
        json={"name": "owned-upload", "source_type": "zip", "upload_id": upload_id},
    )
    assert created.status_code == 200, created.text

    replacement = _upload(client, auth_header, demo_zip)
    assert replacement.status_code == 200, replacement.text
    updated = client.patch(
        f"/api/projects/{created.json()['data']['project']['id']}",
        headers=auth_header,
        json={"upload_id": replacement.json()["data"]["upload_id"]},
    )
    assert updated.status_code == 200, updated.text

    missing = client.post(
        "/api/projects",
        headers=auth_header,
        json={"name": "missing-upload", "source_type": "zip", "upload_id": 999999},
    )
    assert missing.status_code == 404

    other = client.post(
        "/api/auth/register",
        json={"email": "upload-owner-other@example.com", "password": "password123", "nickname": "Other"},
    )
    assert other.status_code == 200, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['data']['access_token']}"}
    forbidden = client.post(
        "/api/projects",
        headers=other_headers,
        json={"name": "foreign-upload", "source_type": "zip", "upload_id": upload_id},
    )
    assert forbidden.status_code == 403


def test_project_rejects_client_storage_key(client, auth_header, demo_zip):
    response = client.post(
        "/api/projects",
        headers=auth_header,
        json={
            "name": "legacy-key",
            "source_type": "zip",
            "zip_object_key": demo_zip["object_key"],
        },
    )
    assert response.status_code == 422



def test_replacing_zip_invalidates_index_and_requires_reparse(client, auth_header, test_database):
    first_upload = client.post(
        "/api/uploads",
        headers=auth_header,
        files={"file": ("old.zip", _source_zip("old.py", "def old_entry():\n    return 1\n"), "application/zip")},
    )
    assert first_upload.status_code == 200, first_upload.text
    project_response = client.post(
        "/api/projects",
        headers=auth_header,
        json={
            "name": "source-revision",
            "source_type": "zip",
            "upload_id": first_upload.json()["data"]["upload_id"],
        },
    )
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["data"]["project"]["id"]

    premature = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=auth_header,
        json={"prompt": "生成流程图", "diagram_type": "flowchart"},
    )
    assert premature.status_code == 409
    assert _task_count(test_database, project_id) == 0

    parsed = client.post(f"/api/projects/{project_id}/parse", headers=auth_header, json={"mode": "sync"})
    assert parsed.status_code == 200, parsed.text
    first_diagram = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=auth_header,
        json={"prompt": "显示旧入口", "diagram_type": "flowchart"},
    )
    assert first_diagram.status_code == 200, first_diagram.text
    diagram_id = first_diagram.json()["data"]["diagram_id"]

    task_count_before_invalid_scope = _task_count(test_database, project_id)
    invalid_scope = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=auth_header,
        json={
            "prompt": "无效文件范围",
            "diagram_type": "flowchart",
            "parameters": {"selectedPaths": ["missing.py"]},
        },
    )
    assert invalid_scope.status_code == 400
    task_count_after_diagram = _task_count(test_database, project_id)
    assert task_count_after_diagram == task_count_before_invalid_scope

    forged_status = client.patch(
        f"/api/projects/{project_id}",
        headers=auth_header,
        json={"status": "ready"},
    )
    assert forged_status.status_code == 422

    replacement = client.post(
        "/api/uploads",
        headers=auth_header,
        files={
            "file": (
                "new.zip",
                _source_zip("new.py", "def new_entry():\n    return 2\n"),
                "application/zip",
            )
        },
    )
    assert replacement.status_code == 200, replacement.text
    updated = client.patch(
        f"/api/projects/{project_id}",
        headers=auth_header,
        json={"upload_id": replacement.json()["data"]["upload_id"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["status"] == "created"
    assert updated.json()["data"]["last_index_version"] is None
    assert client.get(f"/api/diagrams/{diagram_id}", headers=auth_header).json()["data"]["is_outdated"] is True

    stale_analysis = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=auth_header,
        json={"prompt": "不可使用旧索引", "diagram_type": "flowchart"},
    )
    assert stale_analysis.status_code == 409
    assert _task_count(test_database, project_id) == task_count_after_diagram

    reparsed = client.post(f"/api/projects/{project_id}/parse", headers=auth_header, json={"mode": "sync"})
    assert reparsed.status_code == 200, reparsed.text
    with test_database["session_factory"]() as db:
        symbols = {
            item.name
            for item in db.query(Symbol).filter_by(project_id=project_id).all()
        }
    assert "new_entry" in symbols
    assert "old_entry" not in symbols

    fresh_analysis = client.post(
        f"/api/projects/{project_id}/analysis",
        headers=auth_header,
        json={"prompt": "显示新入口", "diagram_type": "flowchart"},
    )
    assert fresh_analysis.status_code == 200, fresh_analysis.text
    assert fresh_analysis.json()["data"]["status"] == "success"
