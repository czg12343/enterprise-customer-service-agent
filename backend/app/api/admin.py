from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.models import AgentRun, Conversation, KnowledgeDocument, Order, Product, ServiceTicket, User
from app.schemas import (
    DashboardStats,
    LLMConfigOut,
    LLMConfigUpdate,
    LLMConnectionTestOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    UserOut,
)
from app.services.llm import LLMProviderError, llm_client
from app.services.runtime_config import (
    LLMRuntimeConfig,
    get_runtime_llm_config,
    save_runtime_llm_config,
)

router = APIRouter(prefix="/admin", tags=["管理后台"])


@router.get("/customers", response_model=list[UserOut])
def customers(
    db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.role == "customer", User.is_active.is_(True))
            .order_by(User.username)
        )
    )


@router.get("/products", response_model=list[ProductOut])
def products(
    keyword: str = Query("", max_length=80),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> list[Product]:
    stmt = select(Product)
    if keyword:
        term = f"%{keyword}%"
        stmt = stmt.where(
            Product.name.ilike(term) | Product.sku.ilike(term) | Product.category.ilike(term)
        )
    return list(db.scalars(stmt.order_by(Product.created_at.desc()).offset(offset).limit(limit)))


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> Product:
    product = Product(**payload.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU 已存在，请更换后重试") from exc
    db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: str,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> Product:
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "stock" in changes and changes["stock"] < product.locked_stock:
        raise HTTPException(status_code=409, detail=f"库存不能低于已锁定库存 {product.locked_stock}")
    for key, value in changes.items():
        setattr(product, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU 已存在，请更换后重试") from exc
    db.refresh(product)
    return product


def _llm_config_out(config: LLMRuntimeConfig) -> LLMConfigOut:
    return LLMConfigOut(
        base_url=config.base_url,
        model=config.model,
        enabled=config.enabled,
        ready=config.ready,
        has_api_key=bool(config.api_key),
        source=config.source,
    )


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(
    db: Session = Depends(get_db), _: User = Depends(require_roles("service", "admin"))
) -> DashboardStats:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return DashboardStats(
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        orders=db.scalar(select(func.count()).select_from(Order)) or 0,
        open_tickets=db.scalar(
            select(func.count()).select_from(ServiceTicket).where(ServiceTicket.status.notin_(["resolved", "closed"]))
        )
        or 0,
        conversations=db.scalar(select(func.count()).select_from(Conversation)) or 0,
        knowledge_documents=db.scalar(select(func.count()).select_from(KnowledgeDocument)) or 0,
        today_agent_runs=db.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.created_at >= today)
        )
        or 0,
    )


@router.get("/llm-config", response_model=LLMConfigOut)
def llm_config(_: User = Depends(require_roles("admin"))) -> LLMConfigOut:
    return _llm_config_out(get_runtime_llm_config())


@router.put("/llm-config", response_model=LLMConfigOut)
def update_llm_config(
    payload: LLMConfigUpdate,
    _: User = Depends(require_roles("admin")),
) -> LLMConfigOut:
    try:
        config = save_runtime_llm_config(**payload.model_dump())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _llm_config_out(config)


@router.post("/llm-config/test", response_model=LLMConnectionTestOut)
def test_llm_config(_: User = Depends(require_roles("admin"))) -> LLMConnectionTestOut:
    try:
        message = llm_client.test_connection()
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return LLMConnectionTestOut(success=True, message=message)
