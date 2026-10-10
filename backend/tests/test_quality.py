from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.cli import create_admin
from app.core.config import Settings, _database_url
from app.core.database import SessionLocal
from app.models import utcnow
from app.services.business import refund_eligibility
from app.services.llm import capture_llm_usage, llm_client
from app.services.runtime_config import LLMRuntimeConfig


def _delivered_order(delivered_at):
    return SimpleNamespace(
        payment_status="paid",
        status="paid",
        shipping_status="delivered",
        logistics=SimpleNamespace(delivered_at=delivered_at),
    )


def test_refund_window_uses_delivery_time():
    eligible, _ = refund_eligibility(
        _delivered_order(datetime.now(UTC) - timedelta(days=6))
    )
    expired, _ = refund_eligibility(
        _delivered_order(datetime.now(UTC) - timedelta(days=8))
    )
    missing, message = refund_eligibility(_delivered_order(None))

    assert eligible is True
    assert expired is False
    assert missing is False
    assert "签收时间" in message


def test_utc_defaults_are_timezone_aware():
    assert utcnow().tzinfo is UTC


def test_production_rejects_demo_seed_and_weak_secret():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings(app_env="production", jwt_secret="weak", auto_seed=False).validate()
    with pytest.raises(RuntimeError, match="AUTO_SEED"):
        Settings(app_env="production", jwt_secret="x" * 40, auto_seed=True).validate()


def test_postgres_url_escapes_password_characters(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_USER", "enterprise")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:word/with spaces")
    monkeypatch.setenv("POSTGRES_DB", "enterprise_agent")

    url = _database_url()

    assert "p%40ss%3Aword%2Fwith+spaces" in url


def test_create_admin_command_creates_admin_role():
    suffix = uuid4().hex[:8]
    user = create_admin(f"admin_{suffix}", f"admin_{suffix}@example.com", "StrongAdmin123!")
    try:
        assert user.role == "admin"
    finally:
        with SessionLocal() as db:
            stored = db.get(type(user), user.id)
            if stored:
                db.delete(stored)
                db.commit()


def test_llm_usage_is_collected_from_provider_response(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "连接成功"}}],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 8,
                    "cost": 0.00042,
                },
            }

    monkeypatch.setattr("app.services.llm.httpx.post", lambda *args, **kwargs: FakeResponse())
    config = LLMRuntimeConfig(
        base_url="https://example.com/v1",
        api_key="test-key",
        model="test-model",
        enabled=True,
        source="test",
    )

    with capture_llm_usage() as usage:
        answer = llm_client._complete(config, [{"role": "user", "content": "test"}])

    assert answer == "连接成功"
    assert len(usage) == 1
    assert usage[0].prompt_tokens == 120
    assert usage[0].completion_tokens == 8
    assert usage[0].total_tokens == 128
    assert usage[0].estimated_cost_usd == pytest.approx(0.00042)
