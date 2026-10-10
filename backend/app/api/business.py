from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models import Logistics, Order, OrderItem, Product, RefundRequest, ServiceTicket, User
from app.schemas import (
    LogisticsUpdate,
    OrderCreate,
    OrderOut,
    ProductOut,
    RefundDecision,
    TicketCreate,
    TicketOut,
    TicketUpdate,
)
from app.services.business import ACTIVE_REFUND_STATUSES, create_ticket

router = APIRouter(tags=["业务"])


def _order_products(db: Session, order: Order) -> dict[str, Product]:
    ids = [item.product_id for item in order.items]
    products = {
        product.id: product
        for product in db.scalars(select(Product).where(Product.id.in_(ids)).with_for_update())
    }
    if len(products) != len(set(ids)):
        raise HTTPException(status_code=409, detail="订单商品数据不完整，请联系管理员处理")
    return products


@router.get("/products", response_model=list[ProductOut])
def products(
    keyword: str = Query("", max_length=80),
    category: str | None = Query(None, max_length=50),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Product]:
    stmt = select(Product).where(Product.is_active.is_(True))
    if keyword:
        term = f"%{keyword}%"
        stmt = stmt.where(
            Product.name.ilike(term) | Product.sku.ilike(term) | Product.description.ilike(term)
        )
    if category:
        stmt = stmt.where(Product.category == category)
    return list(db.scalars(stmt.order_by(Product.created_at.desc()).offset(offset).limit(limit)))


@router.get("/orders", response_model=list[OrderOut])
def orders(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Order]:
    stmt = select(Order).order_by(Order.created_at.desc())
    if user.role == "customer":
        stmt = stmt.where(Order.user_id == user.id)
    return list(db.scalars(stmt.offset(offset).limit(limit)).unique())


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> Order:
    customer = db.scalar(select(User).where(
        User.username == payload.customer_username, User.role == "customer", User.is_active.is_(True)
    ))
    if not customer:
        raise HTTPException(status_code=404, detail="客户账号不存在或已停用")
    ids = [item.product_id for item in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="同一商品请合并数量后录入")
    catalog = {p.id: p for p in db.scalars(select(Product).where(
        Product.id.in_(ids), Product.is_active.is_(True)
    ).with_for_update())}
    if len(catalog) != len(ids):
        raise HTTPException(status_code=422, detail="商品不存在或已下架")
    for item in payload.items:
        product = catalog[item.product_id]
        available_stock = product.stock - product.locked_stock
        if available_stock < item.quantity:
            raise HTTPException(
                status_code=409,
                detail=f"{product.name} 可售库存不足，当前仅剩 {max(0, available_stock)} 件",
            )
    for item in payload.items:
        product = catalog[item.product_id]
        if payload.payment_status == "paid":
            product.stock -= item.quantity
        else:
            product.locked_stock += item.quantity
    # Manual order recording: prices come from the catalog, not the browser.
    order = Order(
        order_no=payload.order_no or f"EM{uuid4().int}"[:32], user_id=customer.id,
        status="paid" if payload.payment_status == "paid" else "pending",
        payment_status=payload.payment_status, shipping_status="pending",
        total_amount=sum((catalog[i.product_id].price * i.quantity for i in payload.items), Decimal("0")),
    )
    order.items = [OrderItem(
        product_id=i.product_id, product_name=catalog[i.product_id].name,
        quantity=i.quantity, unit_price=catalog[i.product_id].price,
    ) for i in payload.items]
    db.add(order)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="订单号已存在，请更换订单号") from exc
    db.refresh(order)
    return order


@router.post("/orders/{order_no}/pay", response_model=OrderOut)
def pay_order(
    order_no: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> Order:
    order = db.scalar(select(Order).where(Order.order_no == order_no).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.payment_status == "paid":
        return order
    if order.status in {"cancelled", "refunded"} or order.payment_status != "pending":
        raise HTTPException(status_code=409, detail="当前订单状态不能确认支付")
    products = _order_products(db, order)
    for item in order.items:
        product = products[item.product_id]
        if product.locked_stock < item.quantity or product.stock < item.quantity:
            raise HTTPException(status_code=409, detail=f"{product.name} 的锁定库存异常，无法确认支付")
    for item in order.items:
        product = products[item.product_id]
        product.locked_stock -= item.quantity
        product.stock -= item.quantity
    order.payment_status = "paid"
    order.status = "paid"
    db.commit()
    db.refresh(order)
    return order


@router.post("/orders/{order_no}/cancel", response_model=OrderOut)
def cancel_order(
    order_no: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> Order:
    order = db.scalar(select(Order).where(Order.order_no == order_no).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == "cancelled":
        return order
    if order.payment_status != "pending" or order.shipping_status != "pending":
        raise HTTPException(status_code=409, detail="只有待支付且未发货的订单可以取消")
    products = _order_products(db, order)
    for item in order.items:
        product = products[item.product_id]
        if product.locked_stock < item.quantity:
            raise HTTPException(status_code=409, detail=f"{product.name} 的锁定库存异常，无法取消订单")
    for item in order.items:
        products[item.product_id].locked_stock -= item.quantity
    order.status = "cancelled"
    order.payment_status = "cancelled"
    db.commit()
    db.refresh(order)
    return order


@router.put("/orders/{order_no}/logistics", response_model=OrderOut)
def update_logistics(
    order_no: str,
    payload: LogisticsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> Order:
    order = db.scalar(select(Order).where(Order.order_no == order_no).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.payment_status != "paid" or order.status in {"cancelled", "refunded"}:
        raise HTTPException(status_code=409, detail="未支付、已取消或已退款订单不能更新物流")
    if order.shipping_status == "delivered" and payload.status != "delivered":
        raise HTTPException(status_code=409, detail="已签收订单不能退回运输状态")
    if payload.status != "delivered" and payload.delivered_at:
        raise HTTPException(status_code=422, detail="只有已签收状态可以填写签收时间")
    now = datetime.now(UTC)
    if payload.delivered_at and payload.delivered_at > now:
        raise HTTPException(status_code=422, detail="签收时间不能晚于当前时间")
    logistics = order.logistics
    if logistics is None:
        logistics = Logistics(order_id=order.id)
        order.logistics = logistics
    previous_delivery = logistics.delivered_at
    for key, value in payload.model_dump(exclude={"status", "delivered_at"}).items():
        setattr(logistics, key, value)
    logistics.status = {
        "shipped": "已发货", "in_transit": "运输中", "out_for_delivery": "派送中", "delivered": "已签收",
    }[payload.status]
    logistics.delivered_at = (payload.delivered_at or previous_delivery or now) if payload.status == "delivered" else None
    order.shipping_status = "delivered" if payload.status == "delivered" else "shipped"
    order.status = order.shipping_status
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="运单号已被其他订单使用") from exc
    db.refresh(order)
    return order


@router.get("/orders/{order_no}", response_model=OrderOut)
def order_detail(
    order_no: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Order:
    stmt = select(Order).where(Order.order_no == order_no)
    if user.role == "customer":
        stmt = stmt.where(Order.user_id == user.id)
    order = db.scalar(stmt)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


@router.get("/tickets", response_model=list[TicketOut])
def tickets(
    ticket_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ServiceTicket]:
    stmt = select(ServiceTicket).order_by(ServiceTicket.created_at.desc())
    if user.role == "customer":
        stmt = stmt.where(ServiceTicket.user_id == user.id)
    if ticket_status:
        stmt = stmt.where(ServiceTicket.status == ticket_status)
    return list(db.scalars(stmt.offset(offset).limit(limit)))


@router.post("/tickets", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def ticket_create(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ServiceTicket:
    if payload.order_no:
        owned = db.scalar(
            select(Order).where(Order.order_no == payload.order_no, Order.user_id == user.id)
        )
        if user.role == "customer" and not owned:
            raise HTTPException(status_code=403, detail="不能为其他用户的订单创建工单")
    ticket = create_ticket(db, user, **payload.model_dump())
    db.commit()
    db.refresh(ticket)
    return ticket


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
def ticket_update(
    ticket_id: str,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("service", "admin")),
) -> ServiceTicket:
    ticket = db.get(ServiceTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")
    changes = payload.model_dump(exclude_unset=True)
    if ticket.category == "refund" and changes.get("status") in {"resolved", "closed"}:
        raise HTTPException(status_code=409, detail="退款工单请使用“完成退款”或“驳回退款”操作")
    assignee_id = changes.get("assignee_id")
    if assignee_id:
        assignee = db.get(User, assignee_id)
        if not assignee or not assignee.is_active or assignee.role not in {"service", "admin"}:
            raise HTTPException(status_code=422, detail="处理人必须是有效的客服或管理员")
    for key, value in changes.items():
        setattr(ticket, key, value)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.post("/tickets/{ticket_id}/refund-decision", response_model=TicketOut)
def decide_refund(
    ticket_id: str,
    payload: RefundDecision,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("service", "admin")),
) -> ServiceTicket:
    ticket = db.get(ServiceTicket, ticket_id)
    if not ticket or ticket.category != "refund" or not ticket.order_no:
        raise HTTPException(status_code=404, detail="退款工单不存在")
    order = db.scalar(select(Order).where(Order.order_no == ticket.order_no).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="关联订单不存在")
    if order.status == "refunded":
        if payload.action != "complete":
            raise HTTPException(status_code=409, detail="该订单已经完成退款")
        return ticket
    refund = db.scalar(
        select(RefundRequest).where(
            RefundRequest.order_id == order.id,
            RefundRequest.status.in_(ACTIVE_REFUND_STATUSES),
        ).with_for_update()
    )
    if not refund:
        raise HTTPException(status_code=409, detail="没有可处理的退款申请")
    if payload.action == "complete":
        products = _order_products(db, order)
        for item in order.items:
            products[item.product_id].stock += item.quantity
        refund.status = "completed"
        order.status = "refunded"
        order.payment_status = "refunded"
        ticket.status = "resolved"
        ticket.result = payload.result or "退款已完成，商品库存已恢复"
    else:
        refund.status = "rejected"
        ticket.status = "closed"
        ticket.result = payload.result or "退款申请未通过"
    db.commit()
    db.refresh(ticket)
    return ticket
