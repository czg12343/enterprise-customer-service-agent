from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, Product, RefundRequest, ServiceTicket, User

ACTIVE_REFUND_STATUSES = ("pending", "approved", "processing")


def product_search(db: Session, keyword: str, limit: int = 5) -> list[Product]:
    term = f"%{keyword.strip()}%"
    return list(
        db.scalars(
            select(Product)
            .where(
                Product.is_active.is_(True),
                (Product.name.ilike(term))
                | (Product.category.ilike(term))
                | (Product.sku.ilike(term)),
            )
            .limit(limit)
        )
    )


def owned_order(db: Session, order_no: str, user: User) -> Order | None:
    stmt = select(Order).where(Order.order_no == order_no)
    if user.role == "customer":
        stmt = stmt.where(Order.user_id == user.id)
    return db.scalar(stmt)


def refund_eligibility(order: Order) -> tuple[bool, str]:
    if order.payment_status != "paid":
        return False, "订单尚未支付，不能发起退款"
    if order.status in {"cancelled", "refunded"}:
        return False, "订单已取消或已退款"
    if order.shipping_status == "delivered":
        delivered_at = order.logistics.delivered_at if order.logistics else None
        if delivered_at is None:
            return False, "订单缺少签收时间，请转人工客服核验退货资格"
        if delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=UTC)
        days = (datetime.now(UTC) - delivered_at).days
        if days > 7:
            return False, "订单已超过七天退货期限"
    return True, "订单符合退款申请条件"


def existing_refund_with_ticket(
    db: Session, user: User, order: Order
) -> tuple[RefundRequest | None, ServiceTicket | None]:
    refund = db.scalar(
        select(RefundRequest).where(
            RefundRequest.order_id == order.id,
            RefundRequest.status.in_(ACTIVE_REFUND_STATUSES),
        )
    )
    if not refund:
        return None, None
    ticket = db.scalar(
        select(ServiceTicket)
        .where(ServiceTicket.user_id == user.id, ServiceTicket.order_no == order.order_no)
        .order_by(ServiceTicket.created_at.desc())
    )
    return refund, ticket


def create_refund_with_ticket(
    db: Session, user: User, order: Order, reason: str, description: str = ""
) -> tuple[RefundRequest, ServiceTicket, bool]:
    existing, ticket = existing_refund_with_ticket(db, user, order)
    if existing:
        if ticket:
            return existing, ticket, False
        ticket = ServiceTicket(
            ticket_no=f"TK{uuid4().hex[:8].upper()}",
            user_id=user.id,
            order_no=order.order_no,
            category="refund",
            title=f"订单 {order.order_no} 退款申请",
            description=description or reason,
            priority="normal",
        )
        db.add(ticket)
        db.flush()
        return existing, ticket, False

    suffix = uuid4().hex[:8].upper()
    refund = RefundRequest(
        refund_no=f"RF{suffix}",
        order_id=order.id,
        user_id=user.id,
        reason=reason,
        description=description,
    )
    ticket = ServiceTicket(
        ticket_no=f"TK{suffix}",
        user_id=user.id,
        order_no=order.order_no,
        category="refund",
        title=f"订单 {order.order_no} 退款申请",
        description=description or reason,
        priority="normal",
    )
    db.add_all([refund, ticket])
    db.flush()
    return refund, ticket, True


def create_ticket(db: Session, user: User, **data: str | None) -> ServiceTicket:
    ticket = ServiceTicket(
        ticket_no=f"TK{uuid4().hex[:8].upper()}",
        user_id=user.id,
        order_no=data.get("order_no"),
        category=data.get("category") or "other",
        title=data.get("title") or "客服咨询",
        description=data.get("description") or "用户通过智能客服创建工单",
        priority=data.get("priority") or "normal",
    )
    db.add(ticket)
    db.flush()
    return ticket
