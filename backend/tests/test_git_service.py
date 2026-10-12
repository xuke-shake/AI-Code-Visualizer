from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.exceptions import AppException
from app.core.config import get_settings
from app.schemas.project import ProjectCreate
from app.services.git_service import GitImportError, GitService, validate_github_repo_url


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/octocat/Hello-World",
        "https://gitlab.com/octocat/Hello-World",
        "git@github.com:octocat/Hello-World.git",
        "ssh://git@github.com/octocat/Hello-World.git",
        "https://user:pass@github.com/octocat/Hello-World",
        "https://github.com:443/octocat/Hello-World",
        "https://github.com/octocat/Hello-World?token=x",
        "https://github.com/octocat/Hello-World/tree/main",
        "https://github.com/../Hello-World",
        "https://github.com/octocat/../../escape",
    ],
)
def test_only_public_github_https_urls_are_accepted(url: str):
    with pytest.raises(ValueError):
        validate_github_repo_url(url)


def test_project_schema_rejects_non_github_git_sources():
    with pytest.raises(ValueError, match="repo_url"):
        ProjectCreate(name="missing", source_type="git")
    with pytest.raises(ValueError):
        ProjectCreate(name="bad", source_type="git", repo_url="https://example.com/repo.git")
    with pytest.raises(ValueError):
        ProjectCreate(name="bad", source_type="git", repo_url="git@github.com:octocat/Hello-World.git")


def test_git_command_has_noninteractive_protocol_and_timeout(monkeypatch, test_database):
    settings = get_settings()
    service = GitService(settings)
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    service._run_git(service._git_command("fetch", "--prune"))

    assert "protocol.file.allow=never" in captured["args"]
    assert "protocol.ext.allow=never" in captured["args"]
    assert "protocol.ssh.allow=never" in captured["args"]
    assert captured["kwargs"]["timeout"] == settings.git_command_timeout_seconds
    assert captured["kwargs"]["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert captured["kwargs"]["env"]["GIT_ASKPASS"] == "false"


def test_validate_and_pack_snapshot_excludes_git_and_rejects_symlinks(test_database, monkeypatch):
    settings = get_settings()
    service = GitService(settings)
    repo = test_database["storage_path"] / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("private", encoding="utf-8")
    (repo / "main.py").write_text("print('ok')\n", encoding="utf-8")

    file_count, total_bytes = service.validate_snapshot(repo)
    assert file_count == 1
    assert total_bytes == (repo / "main.py").stat().st_size
    packed = service.pack_snapshot(repo, 12)
    assert packed.exists()
    from zipfile import ZipFile

    with ZipFile(packed) as archive:
        assert archive.namelist() == ["main.py"]

    outside = test_database["storage_path"] / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = repo / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前 Windows 环境不允许创建符号链接")
    with pytest.raises(GitImportError, match="符号链接"):
        service.validate_snapshot(repo)


def test_clone_failure_does_not_leave_import_temp_or_project_dir(test_database, monkeypatch):
    settings = get_settings()
    service = GitService(settings)

    def fail_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="secret remote details")

    monkeypatch.setattr(subprocess, "run", fail_run)
    with pytest.raises(GitImportError):
        service.clone_for_project("https://github.com/octocat/Hello-World", None, 77)

    assert not (settings.storage_path / "projects" / "77").exists()
    import_root = settings.storage_path / ".git-imports"
    assert not any(import_root.iterdir())


def test_snapshot_resource_limits(test_database, monkeypatch):
    settings = get_settings()
    service = GitService(settings)
    repo = test_database["storage_path"] / "repo-limit"
    repo.mkdir()
    (repo / "a.py").write_text("x", encoding="utf-8")
    (repo / "b.py").write_text("y", encoding="utf-8")

    monkeypatch.setattr(settings, "git_max_snapshot_files", 1)
    with pytest.raises(GitImportError, match="资源限制"):
        service.validate_snapshot(repo)


def test_api_persists_failed_git_import_without_leaving_snapshot(client, auth_header, test_database, monkeypatch):
    from app.api import projects as projects_api
    from app.models.project import Project

    class FailingGitService:
        def clone_for_project(self, repo_url, branch, project_id):
            raise GitImportError("simulated failure")

    monkeypatch.setattr(projects_api, "GitService", FailingGitService)
    response = client.post(
        "/api/projects",
        headers=auth_header,
        json={
            "name": "failed-git",
            "source_type": "git",
            "repo_url": "https://github.com/octocat/Hello-World",
        },
    )
    assert response.status_code == 400
    db = test_database["session_factory"]()
    try:
        project = db.query(Project).filter_by(name="failed-git").one()
        assert project.status == "failed"
    finally:
        db.close()
