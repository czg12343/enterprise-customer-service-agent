from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

TEST_DB = Path(tempfile.gettempdir()) / "enterprise_mind_test.db"
TEST_UPLOADS = Path(tempfile.gettempdir()) / "enterprise_mind_test_uploads"
TEST_LLM_CONFIG = Path(tempfile.gettempdir()) / "enterprise_mind_llm.json"
TEST_DB.unlink(missing_ok=True)
TEST_LLM_CONFIG.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["UPLOAD_DIR"] = str(TEST_UPLOADS)
os.environ["RUNTIME_CONFIG_PATH"] = str(TEST_LLM_CONFIG)
os.environ["AUTO_SEED"] = "true"
os.environ["JWT_SECRET"] = "test-secret-with-at-least-32-bytes-long"

import httpx  # noqa: E402

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_demo  # noqa: E402


class ASGITestClient:
    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async def perform() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(perform())

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)


@pytest.fixture(scope="session")
def client():
    init_db()
    with SessionLocal() as db:
        seed_demo(db)
    return ASGITestClient()


@pytest.fixture()
def customer_headers(client: ASGITestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": "customer", "password": "Customer123!"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client: ASGITestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "Admin123!"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
