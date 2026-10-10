from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db
from app.models import DocumentChunk, KnowledgeAccess, KnowledgeBase, KnowledgeDocument, User
from app.services.knowledge_access import require_base, visible_bases
from app.rag.parser import extract_text, split_text
from app.rag.retriever import hybrid_search
from app.schemas import (
    DocumentContentOut,
    DocumentOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeAccessUpdate,
)

router = APIRouter(prefix="/knowledge", tags=["知识库"])
ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".xlsx", ".csv"}


@router.get("/bases", response_model=list[KnowledgeBaseOut])
def list_bases(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[KnowledgeBaseOut]:
    bases = list(db.scalars(select(KnowledgeBase).where(visible_bases(user)).order_by(KnowledgeBase.created_at.desc())))
    return [
        KnowledgeBaseOut.model_validate(knowledge_base).model_copy(
            update={
                "document_count": db.scalar(
                    select(func.count())
                    .select_from(KnowledgeDocument)
                    .where(KnowledgeDocument.knowledge_base_id == knowledge_base.id)
                )
                or 0,
                "chunk_count": db.scalar(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .where(DocumentChunk.knowledge_base_id == knowledge_base.id)
                )
                or 0,
            }
        )
        for knowledge_base in bases
    ]


@router.post("/bases", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
def create_base(
    payload: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> KnowledgeBase:
    if db.scalar(select(KnowledgeBase).where(KnowledgeBase.name == payload.name)):
        raise HTTPException(status_code=409, detail="知识库名称已存在")
    knowledge_base = KnowledgeBase(**payload.model_dump(exclude={"visibility"}))
    knowledge_base.access = KnowledgeAccess(visibility=payload.visibility)
    db.add(knowledge_base)
    db.commit()
    db.refresh(knowledge_base)
    return knowledge_base


@router.patch("/bases/{base_id}/access", response_model=KnowledgeBaseOut)
def update_access(base_id: str, payload: KnowledgeAccessUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> KnowledgeBase:
    base = require_base(db, base_id, user)
    if base.access is None:
        base.access = KnowledgeAccess(visibility=payload.visibility)
    else:
        base.access.visibility = payload.visibility
    db.commit()
    db.refresh(base)
    return base


@router.get("/bases/{base_id}/documents", response_model=list[DocumentOut])
def list_documents(
    base_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[KnowledgeDocument]:
    require_base(db, base_id, user)
    return list(
        db.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == base_id)
            .order_by(KnowledgeDocument.created_at.desc())
        )
    )


@router.get("/documents/{document_id}", response_model=DocumentContentOut)
def document_content(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentContentOut:
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    knowledge_base = require_base(db, document.knowledge_base_id, user)
    chunks = list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
        )
    )
    payload = DocumentOut.model_validate(document).model_dump()
    return DocumentContentOut(
        **payload,
        knowledge_base_name=knowledge_base.name if knowledge_base else "未知知识库",
        chunks=chunks,
    )


@router.post("/bases/{base_id}/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    base_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> KnowledgeDocument:
    knowledge_base = db.get(KnowledgeBase, base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    safe_name = Path(file.filename or "document.txt").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    target_dir = settings.upload_dir / base_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid4().hex}_{safe_name}"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with target.open("wb") as output:
            while data := file.file.read(1024 * 1024):
                written += len(data)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件不能超过 {settings.max_upload_mb} MB",
                    )
                output.write(data)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    try:
        text = extract_text(target)
        chunks = split_text(text)
        if not chunks:
            raise ValueError("文档中没有可解析文本")
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"文档解析失败: {exc}") from exc
    document = KnowledgeDocument(
        knowledge_base_id=base_id,
        filename=safe_name,
        file_type=suffix.lstrip("."),
        storage_path=str(target),
        status="ready",
        chunk_count=len(chunks),
    )
    db.add(document)
    db.flush()
    for index, chunk in enumerate(chunks):
        db.add(
            DocumentChunk(
                document_id=document.id,
                knowledge_base_id=base_id,
                chunk_index=index,
                **chunk,
            )
        )
    db.commit()
    db.refresh(document)
    return document


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> None:
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    path = Path(document.storage_path)
    db.delete(document)
    db.commit()
    if path.exists() and path.is_file() and settings.upload_dir in path.parents:
        path.unlink(missing_ok=True)


@router.get("/search")
def search_knowledge(
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(5, ge=1, le=20),
    base_id: str | None = Query(None, max_length=32),
    public_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if base_id:
        require_base(db, base_id, user)
    return {"query": q, "results": hybrid_search(db, q, limit, user=None if public_only else user, base_id=base_id)}
