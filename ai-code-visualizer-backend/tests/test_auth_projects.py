from tests.conftest import auth_header


def test_register_login_and_create_project(client):
    headers = auth_header(client)
    login = client.post("/api/auth/login", json={"email": "u@example.com", "password": "password123"})
    assert login.status_code == 200
    assert login.json()["code"] == 0

    resp = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "示例项目", "language": "Python", "source_type": "zip", "zip_object_key": "uploads/1/demo.zip"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["project"]["name"] == "示例项目"

    project_id = data["project"]["id"]
    parse = client.post(f"/api/projects/{project_id}/parse", headers=headers, json={"mode": "sync"})
    assert parse.status_code == 200
    assert parse.json()["data"]["status"] == "success"
