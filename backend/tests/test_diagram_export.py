from tests.conftest import auth_header


def test_analysis_diagram_export(client):
    headers = auth_header(client)
    project = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "图表项目", "language": "Python", "source_type": "zip", "zip_object_key": "uploads/1/demo.zip"},
    ).json()["data"]["project"]

    analysis = client.post(
        f"/api/projects/{project['id']}/analysis",
        headers=headers,
        json={"prompt": "生成登录流程图", "diagram_type": "flowchart", "title": "登录流程"},
    )
    assert analysis.status_code == 200
    diagram_id = analysis.json()["data"]["diagram_id"]

    diagram = client.get(f"/api/diagrams/{diagram_id}", headers=headers)
    assert diagram.status_code == 200
    assert "flowchart" in diagram.json()["data"]["mermaid_code"]

    export = client.post(f"/api/diagrams/{diagram_id}/export", headers=headers, json={"format": "markdown"})
    assert export.status_code == 200
    assert export.json()["data"]["object_key"].endswith(".md")
