from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.customer_service import run_customer_agent
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import AgentRun, Conversation, Message, User, utcnow
from app.services.knowledge_access import allowed_document_ids
from app.schemas import (
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    FeedbackRequest,
    MessageOut,
)

router = APIRouter(prefix="/chat", tags=["智能客服"])


def _owned_conversation(db: Session, conversation_id: str, user: User) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


def _chat(db: Session, conversation: Conversation, user: User, content: str) -> Message:
    user_message = Message(conversation_id=conversation.id, role="user", content=content)
    db.add(user_message)
    db.flush()
    if conversation.status in {"waiting_human", "human_active"}:
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=(
                "你的补充消息已加入人工客服队列，请稍候。"
                if conversation.status == "waiting_human"
                else "消息已发送给人工客服，请等待回复。"
            ),
            intent="human",
            tool_calls=[{"name": "queue_human_message", "arguments": {}, "status": "success"}],
        )
        conversation.updated_at = utcnow()
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)
        return assistant_message
    result = run_customer_agent(db, user, conversation, content)
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result.get("response", "暂时无法处理该请求。"),
        intent=result.get("intent"),
        sources=result.get("sources", []),
        tool_calls=result.get("tool_calls", []),
    )
    if conversation.title == "新会话":
        conversation.title = content[:30]
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    return assistant_message


@router.get("/conversations", response_model=list[ConversationOut])
def conversations(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
        )
    )


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    conversation = Conversation(user_id=user.id, title=payload.title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    conversation = _owned_conversation(db, conversation_id, user)
    db.query(AgentRun).filter(AgentRun.conversation_id == conversation.id).delete()
    db.query(Message).filter(Message.conversation_id == conversation.id).delete()
    db.delete(conversation)
    db.commit()


@router.post("/conversations/{conversation_id}/return-to-bot", response_model=ConversationOut)
def return_to_bot(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conversation = _owned_conversation(db, conversation_id, user)
    context = dict(conversation.context or {})
    handoff = dict(context.pop("handoff", {}) or {})
    context["last_handoff"] = {**handoff, "ended_at": utcnow().isoformat(), "ended_by": user.id}
    changed = db.execute(update(Conversation).where(Conversation.id == conversation.id, Conversation.status.in_(["waiting_human", "human_active"])).values(status="bot", context=context, updated_at=utcnow()))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="会话已由智能客服处理，请刷新")
    db.add(Message(conversation_id=conversation.id, role="assistant", intent="human", content="已结束本次人工服务，智能客服已恢复。"))
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MessageOut]:
    conversation = _owned_conversation(db, conversation_id, user)
    history = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        )
    )
    document_ids = {source.get("document_id") for message in history for source in message.sources or []}
    allowed = allowed_document_ids(db, user, document_ids)
    results = []
    for message in history:
        output = MessageOut.model_validate(message)
        if any(source.get("document_id") not in allowed for source in message.sources or []):
            output = output.model_copy(update={"content": "该回答引用的文档已不可访问，请重新提问。", "sources": [], "tool_calls": []})
        results.append(output)
    return results


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut)
def send_message(
    conversation_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Message:
    conversation = _owned_conversation(db, conversation_id, user)
    return _chat(db, conversation, user, payload.content)


@router.post("/conversations/{conversation_id}/stream")
def stream_message(
    conversation_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    conversation = _owned_conversation(db, conversation_id, user)
    message = _chat(db, conversation, user, payload.content)
    message_data = MessageOut.model_validate(message).model_dump(mode="json")

    async def event_stream():
        for character in message.content:
            yield f"data: {json.dumps({'type': 'delta', 'content': character}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)
        yield f"data: {json.dumps({'type': 'done', 'message': message_data}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/messages/{message_id}/feedback", response_model=MessageOut)
def message_feedback(
    message_id: str,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Message:
    message = db.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.id == message_id, Conversation.user_id == user.id)
    )
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")
    message.feedback = payload.value
    db.commit()
    db.refresh(message)
    return message
