from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from app.core.config import Settings, get_settings


_GITHUB_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class GitImportError(Exception):
    """内部 Git 导入失败，不携带命令 stderr 给客户端。"""


def validate_github_repo_url(value: str) -> str:
    """只允许无凭据的公开 GitHub HTTPS 仓库地址。"""

    if not isinstance(value, str) or not value:
        raise ValueError("Git项目必须提供仓库地址")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("repo_url必须是GitHub HTTPS仓库地址") from exc

    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("repo_url仅支持无凭据的https://github.com/<owner>/<repo>地址")

    path = unquote(parsed.path)
    if not path.startswith("/"):
        raise ValueError("repo_url必须包含GitHub owner和repo")
    parts = path.strip("/").split("/")
    if len(parts) != 2 or not all(_GITHUB_PART_RE.fullmatch(part) for part in parts):
        raise ValueError("repo_url必须是https://github.com/<owner>/<repo>格式")
    if parts[0] in {".", ".."} or parts[1] in {".", ".."}:
        raise ValueError("repo_url包含非法路径")
    return value


class GitService:
    """受限的 Git clone、更新和源码快照服务。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def projects_root(self) -> Path:
        root = self.settings.storage_path / "projects"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def project_path(self, project_id: int) -> Path:
        if project_id <= 0:
            raise GitImportError("项目目录标识无效")
        return self.projects_root / str(project_id)

    def remove_project_path(self, project_id: int) -> None:
        path = self.project_path(project_id)
        try:
            resolved = path.resolve(strict=False)
            if resolved.parent != self.projects_root.resolve() or path.is_symlink():
                return
            if path.is_dir():
                shutil.rmtree(path)
        except OSError:
            pass

    def _git_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": "false",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_HTTP_LOW_SPEED_LIMIT": "1024",
                "GIT_HTTP_LOW_SPEED_TIME": str(self.settings.git_low_speed_seconds),
            }
        )
        return env

    def _git_command(self, *args: str) -> list[str]:
        # URL/schema层已经只允许 https；这里继续关闭 file/ext/ssh，避免 Git
        # 配置或子模块把命令转向本地文件、外部命令或 SSH。
        return [
            "git",
            "-c",
            "protocol.file.allow=never",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "protocol.ssh.allow=never",
            *args,
        ]

    def _run_git(self, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                cwd=str(cwd) if cwd else None,
                check=True,
                capture_output=True,
                text=True,
                env=self._git_environment(),
                timeout=self.settings.git_command_timeout_seconds,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            raise GitImportError("Git命令执行失败") from exc

    def clone_for_project(self, repo_url: str, branch: str | None, project_id: int) -> Path:
        validate_github_repo_url(repo_url)
        final_dir = self.project_path(project_id)
        if final_dir.exists():
            raise GitImportError("项目 Git 目录已存在")

        import_root = self.settings.storage_path / ".git-imports"
        import_root.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix=f".project-{project_id}-", dir=import_root))
        temp_repo = temp_root / "repo"
        try:
            args = self._git_command("clone", "--depth", "1", "--no-tags", "--no-recurse-submodules")
            if branch:
                args.extend(["--branch", branch])
            args.extend([repo_url, str(temp_repo)])
            self._run_git(args)
            self.validate_snapshot(temp_repo)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            temp_repo.replace(final_dir)
            return final_dir
        except GitImportError:
            raise
        except (OSError, ValueError) as exc:
            raise GitImportError("Git仓库快照不可用") from exc
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def update_repository(self, project_dir: Path) -> None:
        self.validate_snapshot(project_dir)
        self._run_git(self._git_command("pull", "--ff-only", "--no-edit"), cwd=project_dir)
        self.validate_snapshot(project_dir)

    @staticmethod
    def _inside(root: Path, candidate: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False

    def validate_snapshot(self, project_dir: Path) -> tuple[int, int]:
        try:
            root = project_dir.resolve(strict=True)
        except OSError as exc:
            raise GitImportError("未找到 Git 仓库快照") from exc
        if not root.is_dir() or project_dir.is_symlink():
            raise GitImportError("Git仓库快照目录无效")

        max_files = self.settings.git_max_snapshot_files
        max_total_bytes = self.settings.git_max_snapshot_size_mb * 1024 * 1024
        max_file_bytes = self.settings.git_max_snapshot_file_size_mb * 1024 * 1024
        file_count = 0
        total_bytes = 0

        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for name in dirs:
                entry = current_path / name
                if name == ".git":
                    if entry.is_symlink():
                        raise GitImportError("Git仓库包含符号链接")
                    continue
                if entry.is_symlink():
                    raise GitImportError("Git仓库包含符号链接")
                resolved = entry.resolve(strict=True)
                if not self._inside(root, resolved):
                    raise GitImportError("Git仓库路径越界")
                kept_dirs.append(name)
            dirs[:] = kept_dirs

            for name in files:
                entry = current_path / name
                if name == ".git":
                    # Git worktrees may represent .git as a gitfile; it is
                    # metadata and must never enter the analyzed snapshot.
                    if entry.is_symlink():
                        raise GitImportError("Git仓库包含符号链接")
                    continue
                if entry.is_symlink():
                    raise GitImportError("Git仓库包含符号链接")
                resolved = entry.resolve(strict=True)
                if not self._inside(root, resolved) or not entry.is_file():
                    raise GitImportError("Git仓库包含不支持的文件类型")
                size = entry.stat().st_size
                if size > max_file_bytes:
                    raise GitImportError("Git仓库单个文件超过限制")
                file_count += 1
                total_bytes += size
                if file_count > max_files or total_bytes > max_total_bytes:
                    raise GitImportError("Git仓库快照超过资源限制")
        return file_count, total_bytes

    def pack_snapshot(self, project_dir: Path, project_id: int) -> Path:
        self.validate_snapshot(project_dir)
        snapshot_dir = self.settings.storage_path / "snapshots" / str(project_id)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".snapshot-", suffix=".zip", dir=snapshot_dir)
        os.close(fd)
        temp_path = Path(temp_name)
        target = snapshot_dir / f"snapshot-{uuid4().hex}.zip"
        root = project_dir.resolve(strict=True)
        try:
            with ZipFile(temp_path, "w", compression=ZIP_DEFLATED) as archive:
                for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
                    current_path = Path(current)
                    dirs[:] = [name for name in dirs if name != ".git"]
                    for name in files:
                        entry = current_path / name
                        if name == ".git":
                            continue
                        if entry.is_symlink():
                            raise GitImportError("Git仓库包含符号链接")
                        resolved = entry.resolve(strict=True)
                        if not self._inside(root, resolved):
                            raise GitImportError("Git仓库路径越界")
                        archive.write(entry, entry.relative_to(root).as_posix())
            os.replace(temp_path, target)
            return target
        except GitImportError:
            raise
        except (OSError, ValueError) as exc:
            raise GitImportError("Git仓库打包失败") from exc
        finally:
            temp_path.unlink(missing_ok=True)
