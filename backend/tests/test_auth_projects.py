def test_register_login_and_create_project(client, demo_zip, auth_header):
    headers = auth_header
    login = client.post("/api/auth/login", json={"email": "u@example.com", "password": "password123"})
    assert login.status_code == 200
    assert login.json()["code"] == 0

    upload = client.post(
        "/api/uploads",
        headers=headers,
        files={"file": ("demo.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    upload_data = upload.json()["data"]
    assert upload_data["upload_id"] > 0
    assert "object_key" not in upload_data

    resp = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "示例项目",
            "language": "Python",
            "source_type": "zip",
            "upload_id": upload_data["upload_id"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["project"]["name"] == "示例项目"

    project_id = data["project"]["id"]
    parse = client.post(f"/api/projects/{project_id}/parse", headers=headers, json={"mode": "sync"})
    assert parse.status_code == 200
    assert parse.json()["data"]["status"] == "success"
