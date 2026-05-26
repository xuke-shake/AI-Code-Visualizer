import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["STORAGE_DIR"] = "/tmp/ai-code-visualizer-test-storage"

from app.core.database import Base, get_db  # noqa: E402
import app.models  # noqa: F401,E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth_header(client: TestClient) -> dict:
    resp = client.post("/api/auth/register", json={"email": "u@example.com", "password": "password123", "nickname": "User"})
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
