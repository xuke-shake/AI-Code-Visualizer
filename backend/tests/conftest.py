"""共享的后端测试 fixtures。

测试必须使用临时数据库和临时存储，不能依赖开发环境的 ``dev.db`` 或
仓库外部的上传文件。每个测试函数都会得到一份新的 SQLite 数据库。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# 这些环境变量必须在导入 app.core.database 之前设置。即使被测模块意外
# 使用了全局 SessionLocal，也只能落到内存库，绝不会连接开发数据库。
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="ai-code-visualizer-import-")
os.environ["LLM_ENABLED"] = "off"

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
import app.models  # noqa: F401,E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def test_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """创建每个测试独立的 SQLite 文件数据库和存储目录。"""

    database_path = tmp_path / "test.sqlite3"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_test_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    # get_settings() 是缓存对象；仅在当前 fixture 生命周期内替换存储目录，
    # 让应用代码和测试使用同一个临时目录。
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_dir", str(storage_path))

    try:
        yield {
            "engine": engine,
            "session_factory": testing_session_local,
            "database_path": database_path,
            "storage_path": storage_path,
        }
    finally:
        engine.dispose()


@pytest.fixture()
def db_session(test_database: dict):
    """显式的独立测试 Session，供服务层测试直接使用。"""

    db: Session = test_database["session_factory"]()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def demo_zip(test_database: dict) -> dict[str, Path | str]:
    """在当前测试的临时存储中创建一个可解析的演示 ZIP。"""

    # 保留 API 测试原本使用的对象键，但文件只存在于本次测试的临时目录。
    object_key = "uploads/1/demo.zip"
    zip_path = test_database["storage_path"] / object_key
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "demo.py",
            """from helpers import greet\n\n\ndef main(name: str = \"world\") -> str:\n    return greet(name)\n""",
        )
        archive.writestr(
            "helpers.py",
            """def greet(name: str) -> str:\n    return f\"Hello, {name}\"\n""",
        )
        archive.writestr("README.md", "# isolated demo\n")

    return {"path": zip_path, "object_key": object_key}


@pytest.fixture()
def client(test_database: dict, demo_zip: dict) -> TestClient:
    """使用当前测试数据库和临时存储的 FastAPI client。"""

    session_factory = test_database["session_factory"]

    def override_get_db():
        db: Session = session_factory()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def auth_header(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": "u@example.com", "password": "password123", "nickname": "User"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
