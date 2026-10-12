def test_analysis_diagram_export(client, demo_zip, auth_header):
    headers = auth_header
    upload = client.post(
        "/api/uploads",
        headers=headers,
        files={"file": ("demo.zip", demo_zip["path"].read_bytes(), "application/zip")},
    )
    assert upload.status_code == 200, upload.text
    upload_id = upload.json()["data"]["upload_id"]
    project = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "图表项目",
            "language": "Python",
            "source_type": "zip",
            "upload_id": upload_id,
        },
    ).json()["data"]["project"]

    parsed = client.post(f"/api/projects/{project['id']}/parse", headers=headers, json={"mode": "sync"})
    assert parsed.status_code == 200, parsed.text

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
    export_data = export.json()["data"]
    assert export_data["object_key"].endswith(".md")
    assert export_data["download_url"].startswith(f"/api/diagrams/{diagram_id}/export/")

    download = client.get(export_data["download_url"], headers=headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/markdown")
    assert "```mermaid" in download.text

    anonymous = client.get(export_data["download_url"])
    assert anonymous.status_code == 401

    # 导出目录不再匿名挂载；旧 /static URL 不应暴露同一文件。
    old_static_url = f"/static/{export_data['object_key']}"
    assert client.get(old_static_url).status_code == 404

    # 另一个用户可以访问 API，但不能下载当前项目的导出文件。
    second_user = client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "password123", "nickname": "Other"},
    )
    assert second_user.status_code == 200, second_user.text
    other_headers = {"Authorization": f"Bearer {second_user.json()['data']['access_token']}"}
    forbidden = client.get(export_data["download_url"], headers=other_headers)
    assert forbidden.status_code == 403

    # 下载路由只接受当前图表导出目录中的已存在文件。
    missing = client.get(f"/api/diagrams/{diagram_id}/export/not-generated.md", headers=headers)
    assert missing.status_code == 404

    for image_format in ("svg", "png", "pdf"):
        unsupported = client.post(
            f"/api/diagrams/{diagram_id}/export",
            headers=headers,
            json={"format": image_format},
        )
        assert unsupported.status_code == 400
        assert image_format.upper() in unsupported.json()["message"]
        assert "前端" in unsupported.json()["message"]


def test_same_filename_exports_are_isolated_by_diagram(client, demo_zip, auth_header):
    headers = auth_header
    upload = client.post("/api/uploads", headers=headers, files={"file": ("demo.zip", demo_zip["path"].read_bytes(), "application/zip")})
    project = client.post("/api/projects", headers=headers, json={"name": "同名导出", "source_type": "zip", "upload_id": upload.json()["data"]["upload_id"]}).json()["data"]["project"]
    parsed = client.post(f"/api/projects/{project['id']}/parse", headers=headers, json={"mode": "sync"})
    assert parsed.status_code == 200, parsed.text
    ids = []
    for title in ("A", "B"):
        response = client.post(f"/api/projects/{project['id']}/analysis", headers=headers, json={"prompt": title, "diagram_type": "flowchart", "title": title})
        ids.append(response.json()["data"]["diagram_id"])
    links = []
    for diagram_id in ids:
        result = client.post(f"/api/diagrams/{diagram_id}/export", headers=headers, json={"format": "markdown", "filename": "report"})
        links.append(result.json()["data"])
    assert links[0]["object_key"] != links[1]["object_key"]
    assert "# A" in client.get(links[0]["download_url"], headers=headers).text
    assert "# B" in client.get(links[1]["download_url"], headers=headers).text
