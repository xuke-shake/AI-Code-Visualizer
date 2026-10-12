"""IndexService 的隔离解析与同步测试。

这里保留原测试覆盖的两条行为：全量解析和同一 ZIP 的增量同步。
测试数据全部由 fixture 创建，导入本模块不会创建 Session、清理表或读取
项目外部文件。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import subprocess
import sys

from app.models.analysis_task import AnalysisTask
from app.models.project import Project
from app.models.repository import Repository
from app.models.upload import Upload
from app.models.user import User
from app.services.index_service import IndexService


def _create_project(db, demo_zip: dict) -> tuple[User, Project]:
    now = datetime.now(timezone.utc)
    user = User(
        email="parser@example.com",
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
        name="isolated-parser-project",
        source_type="zip",
        status="created",
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    db.flush()
    db.add(
        Repository(
            project_id=project.id,
            upload_id=upload.id,
            created_at=now,
        )
    )
    db.flush()
    return user, project


def test_import_does_not_open_configured_database(tmp_path: Path):
    """单独导入测试模块时，不应创建 Session 或打开配置的数据库。"""

    database_path = tmp_path / "missing-parent" / "business.sqlite3"
    module_path = Path(__file__).resolve()
    backend_path = module_path.parents[1]
    import_code = (
        "import importlib.util; "
        f"spec = importlib.util.spec_from_file_location('isolated_test_parsing', {str(module_path)!r}); "
        "module = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(module)"
    )
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    env["STORAGE_DIR"] = str(tmp_path / "import-storage")
    env["PYTHONPATH"] = str(backend_path)

    completed = subprocess.run(
        [sys.executable, "-c", import_code],
        cwd=backend_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not database_path.exists()


def test_parse_full_and_sync_in_isolated_storage(db_session, demo_zip):
    _, project = _create_project(db_session, demo_zip)
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
    assert project.status == "ready"
    assert parsed.progress == 100

    # 通过 ORM 查询验证 ZIP 中的 Python 和文档文件都进入了隔离数据库。
    from app.models.code_chunk import CodeChunk
    from app.models.source_file import SourceFile
    from app.models.symbol import Symbol

    assert db_session.query(SourceFile).filter_by(project_id=project.id).count() == 3
    assert db_session.query(Symbol).filter_by(project_id=project.id).count() >= 2
    assert db_session.query(CodeChunk).filter_by(project_id=project.id).count() >= 2

    sync_task = AnalysisTask(
        project_id=project.id,
        user_id=project.owner_id,
        task_type="sync",
        status="pending",
        progress=0,
    )
    db_session.add(sync_task)
    db_session.flush()

    synced = IndexService(db_session).sync_incremental(project, sync_task)
    assert synced.status == "success"
    assert synced.result_json["added"] == []
    assert synced.result_json["modified"] == []
    assert synced.result_json["deleted"] == []
    assert db_session.query(SourceFile).filter_by(project_id=project.id).count() == 3
