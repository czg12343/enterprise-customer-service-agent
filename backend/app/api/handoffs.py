from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.models import Conversation, Message, User
from app.schemas import ChatRequest, HandoffConversationOut, MessageOut

router = APIRouter(prefix="/handoffs", tags=["人工客服接管"])


def _handoff_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.status not in {"waiting_human", "human_active"}:
        raise HTTPException(status_code=404, detail="待接入会话不存在或已结束")
    return conversation


def _assignee(conversation: Conversation) -> str | None:
    return (conversation.context or {}).get("handoff", {}).get("assignee_id")


@router.get("", response_model=list[HandoffConversationOut])
def handoff_queue(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("service", "admin")),
) -> list[HandoffConversationOut]:
    conversations = list(
        db.scalars(
            select(Conversation)
            .where(Conversation.status.in_(["waiting_human", "human_active"]))
            .order_by(Conversation.updated_at.desc())
        )
    )
    results: list[HandoffConversationOut] = []
    for conversation in conversations:
        customer = db.get(User, conversation.user_id)
        latest = db.scalar(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        results.append(
            HandoffConversationOut(
                id=conversation.id,
                title=conversation.title,
                status=conversation.status,
                customer_name=customer.username if customer else "未知用户",
                assignee_id=_assignee(conversation),
                latest_message=(latest.content[:120] if latest else ""),
                updated_at=conversation.updated_at,
            )
        )
    return results


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def handoff_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("service", "admin")),
) -> list[Message]:
    conversation = _handoff_conversation(db, conversation_id)
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        )
    )


@router.post("/{conversation_id}/takeover", response_model=HandoffConversationOut)
def take_over(
    conversation_id: str,
    db: Session = Depends(get_db),
    agent: User = Depends(require_roles("service", "admin")),
) -> HandoffConversationOut:
    conversation = _handoff_conversation(db, conversation_id)
    assigned_to = _assignee(conversation)
    if assigned_to and assigned_to != agent.id:
        raise HTTPException(status_code=409, detail="该会话已被其他客服接管")
    context = dict(conversation.context or {})
    context["handoff"] = {
        "assignee_id": agent.id,
        "assignee_name": agent.username,
        "started_at": datetime.now(UTC).isoformat(),
    }
    if conversation.status == "human_active":
        return HandoffConversationOut(id=conversation.id, title=conversation.title, status=conversation.status, customer_name=(db.get(User, conversation.user_id) or agent).username, assignee_id=agent.id, latest_message="人工客服已接入", updated_at=conversation.updated_at)
    changed = db.execute(update(Conversation).where(Conversation.id == conversation.id, Conversation.status == "waiting_human").values(context=context, status="human_active", updated_at=datetime.now(UTC)))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="会话已被接管或已结束，请刷新")
    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=f"人工客服 {agent.username} 已接入，会继续为你处理。",
            intent="human",
            tool_calls=[{"name": "human_takeover", "arguments": {"agent": agent.username}, "status": "success"}],
        )
    )
    db.commit()
    return HandoffConversationOut(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status,
        customer_name=(db.get(User, conversation.user_id) or agent).username,
        assignee_id=agent.id,
        latest_message=f"人工客服 {agent.username} 已接入",
        updated_at=conversation.updated_at,
    )


@router.post("/{conversation_id}/messages", response_model=MessageOut)
def agent_reply(
    conversation_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    agent: User = Depends(require_roles("service", "admin")),
) -> Message:
    conversation = _handoff_conversation(db, conversation_id)
    if conversation.status != "human_active":
        raise HTTPException(status_code=409, detail="请先接管该会话")
    if _assignee(conversation) != agent.id:
        raise HTTPException(status_code=403, detail="只能回复自己接管的会话")
    message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=payload.content,
        intent="human",
        tool_calls=[{"name": "human_reply", "arguments": {"agent": agent.username}, "status": "success"}],
    )
    conversation.updated_at = datetime.now(UTC)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


@router.post("/{conversation_id}/close", response_model=MessageOut)
def close_handoff(
    conversation_id: str,
    db: Session = Depends(get_db),
    agent: User = Depends(require_roles("service", "admin")),
) -> Message:
    conversation = _handoff_conversation(db, conversation_id)
    assigned_to = _assignee(conversation)
    if assigned_to and assigned_to != agent.id and agent.role != "admin":
        raise HTTPException(status_code=403, detail="只能结束自己接管的会话")
    context = dict(conversation.context or {})
    handoff = dict(context.get("handoff") or {})
    handoff["ended_at"] = datetime.now(UTC).isoformat()
    handoff["ended_by"] = agent.id
    context["handoff"] = handoff
    conversation.context = context
    conversation.status = "bot"
    conversation.updated_at = datetime.now(UTC)
    message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="本次人工服务已结束。如有其他问题，可以继续由智能客服为你处理。",
        intent="human",
        tool_calls=[{"name": "human_handoff_closed", "arguments": {"agent": agent.username}, "status": "success"}],
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
