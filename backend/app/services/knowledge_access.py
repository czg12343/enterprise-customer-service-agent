from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeAccess, KnowledgeBase, KnowledgeDocument, User


def visible_bases(user: User | None):
    active = KnowledgeBase.is_active.is_(True)
    if user and user.role in {"admin", "service"}:
        return active
    return active & KnowledgeBase.id.in_(select(KnowledgeAccess.base_id).where(KnowledgeAccess.visibility == "public"))


def allowed_document_ids(db: Session, user: User, ids) -> set[str]:
    return set(db.scalars(select(KnowledgeDocument.id).join(KnowledgeBase).where(KnowledgeDocument.id.in_([value for value in ids if value]), visible_bases(user))))


def require_base(db: Session, base_id: str, user: User) -> KnowledgeBase:
    base = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == base_id, visible_bases(user)))
    if base is None:
        raise HTTPException(status_code=404, detail="知识库不存在或无访问权限")
    return base
