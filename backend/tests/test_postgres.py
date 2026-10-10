from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models import (
    AgentRun,
    Conversation,
    Message,
    User,
)

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")


@pytest.fixture(scope="module")
def postgres_engine():
    assert POSTGRES_URL is not None
    database_name = make_url(POSTGRES_URL).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("TEST_POSTGRES_URL 必须指向名称以 _test 结尾的专用数据库")

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    previous_url = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = POSTGRES_URL
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        if previous_url is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = previous_url


def test_alembic_creates_expected_postgres_schema(postgres_engine):
    tables = set(inspect(postgres_engine).get_table_names())
    assert {"users", "conversations", "messages", "agent_runs", "alembic_version"} <= tables


def test_postgres_cascades_conversation_records(postgres_engine):
    with Session(postgres_engine) as db:
        user = User(
            username="postgres_test",
            email="postgres_test@example.com",
            password_hash="test-only",
            role="customer",
        )
        db.add(user)
        db.flush()
        conversation = Conversation(user_id=user.id, title="PostgreSQL cascade")
        db.add(conversation)
        db.flush()
        db.add_all(
            [
                Message(conversation_id=conversation.id, role="user", content="hello"),
                AgentRun(
                    conversation_id=conversation.id,
                    user_id=user.id,
                    intent="general",
                ),
            ]
        )
        db.commit()
        conversation_id = conversation.id
        db.delete(conversation)
        db.commit()

        messages = db.scalar(
            select(func.count()).select_from(Message).where(
                Message.conversation_id == conversation_id
            )
        )
        runs = db.scalar(
            select(func.count()).select_from(AgentRun).where(
                AgentRun.conversation_id == conversation_id
            )
        )
        assert messages == 0
        assert runs == 0
