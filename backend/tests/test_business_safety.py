"""Regression coverage for confirmation boundaries and repeated human handoffs."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.agents.customer_service import run_customer_agent
from app.api.handoffs import close_handoff, handoff_queue, take_over
from app.core.database import Base
from app.models import Conversation, Order, RefundRequest, ServiceTicket, User


@pytest.fixture()
def business_case():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        customer = User(username="buyer", email="buyer@example.test", password_hash="unused")
        first = User(username="first", email="first@example.test", password_hash="unused", role="service")
        second = User(username="second", email="second@example.test", password_hash="unused", role="service")
        db.add_all([customer, first, second])
        db.flush()
        order = Order(order_no="EM20990101001", user_id=customer.id, total_amount=100, status="shipped")
        conversation = Conversation(user_id=customer.id, title="Safety regression")
        db.add_all([order, conversation])
        db.commit()
        yield db, customer, conversation, order, first, second
    engine.dispose()


@pytest.mark.parametrize("reply", [
    "不要确认提交，我还要考虑", "我不同意", "确认提交吗？", "如果可以再确认提交",
    "稍后确认提交", "回复“确认提交”是什么意思", "确认", "提交", "是的", "同意",
])
def test_refund_rejects_ambiguous_confirmation(business_case, reply):
    db, customer, conversation, order, *_ = business_case
    for query in ("我要退货", order.order_no, "耳机有杂音"):
        run_customer_agent(db, customer, conversation, query)
    run_customer_agent(db, customer, conversation, reply)
    assert db.scalar(select(func.count()).select_from(RefundRequest)) == 0
    assert db.scalar(select(func.count()).select_from(ServiceTicket)) == 0
    assert conversation.context["refund"]["awaiting"] == "confirm"


@pytest.mark.parametrize("reply", ["确认提交", "  确认提交。  ", "确认提交！"])
def test_refund_explicit_confirmation_creates_one_application(business_case, reply):
    db, customer, conversation, order, *_ = business_case
    for query in ("我要退货", order.order_no, "耳机有杂音", reply):
        run_customer_agent(db, customer, conversation, query)
    assert db.scalar(select(func.count()).select_from(RefundRequest)) == 1
    assert db.scalar(select(func.count()).select_from(ServiceTicket)) == 1
    assert "refund" not in conversation.context


def test_second_handoff_can_be_taken_by_another_agent(business_case):
    db, customer, conversation, _, first, second = business_case
    run_customer_agent(db, customer, conversation, "我要转人工客服")
    take_over(conversation.id, db, first)
    with pytest.raises(HTTPException) as conflict:
        take_over(conversation.id, db, second)
    assert conflict.value.status_code == 409
    close_handoff(conversation.id, db, first)
    run_customer_agent(db, customer, conversation, "再次转人工客服")
    queued = next(item for item in handoff_queue(db, second) if item.id == conversation.id)
    assert queued.assignee_id is None
    result = take_over(conversation.id, db, second)
    assert result.assignee_id == second.id
    assert result.status == "human_active"
    assert "ended_at" not in conversation.context["handoff"]
