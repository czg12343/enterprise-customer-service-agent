from __future__ import annotations

import re
import time
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.routing import TOOLS, RouteDecision
from app.models import AgentRun, Conversation, Message, Product, ServiceTicket, User
from app.rag.retriever import hybrid_search
from app.services.business import (
    create_refund_with_ticket,
    create_ticket,
    existing_refund_with_ticket,
    owned_order,
    product_search,
    refund_eligibility,
)
from app.services.llm import capture_llm_usage, llm_client
from app.services.knowledge_access import allowed_document_ids

ORDER_PATTERN = re.compile(r"(?:订单号?[：:\s]*)?([A-Z]{2,5}\d{6,}|EM\d+)", re.IGNORECASE)
INJECTION_MARKERS = (
    "ignore previous",
    "忽略之前",
    "system prompt",
    "系统提示词",
    "drop table",
    "delete from",
)
REFUND_CANCEL_MARKERS = ("取消退货", "取消退款", "不退了", "不用退了", "算了", "先不退", "停止退货")
# Only the advertised standalone command authorizes a business write.
# Substring matching also accepts negations, questions and quoted instructions.
REFUND_CONFIRM_PATTERN = re.compile(r"确认提交[。.!！]?")
CASUAL_MARKERS = (
    "你好",
    "您好",
    "在吗",
    "你是谁",
    "你叫什么",
    "会什么",
    "能做什么",
    "别的",
    "谢谢",
)
PRODUCT_TERMS = ("手机", "耳机", "键盘", "鼠标", "显示器")
PRODUCT_CATALOG_MARKERS = (
    "商品列表",
    "产品列表",
    "全部商品",
    "全部产品",
    "有哪些商品",
    "有哪些产品",
    "推荐商品",
)
TROUBLESHOOTING_MARKERS = (
    "无声音",
    "没声音",
    "没有声音",
    "听不到声音",
    "杂音",
    "断连",
    "连接不上",
    "无法连接",
    "充不了电",
    "无法充电",
    "不能开机",
    "无法开机",
    "黑屏",
    "闪屏",
    "无信号",
    "按键失灵",
    "失灵",
    "故障",
    "坏了",
)
SHORT_FOLLOWUPS = ("?", "？", "为什么", "怎么办", "然后呢", "继续", "具体呢", "怎么处理", "是吗")
CONTEXT_FOLLOWUP_MARKERS = (
    "怎么会",
    "怎么回事",
    "为什么会",
    "那怎么办",
    "还没",
    "还没有",
    "正常吗",
    "怎么这样",
)


def _is_short_followup(query: str) -> bool:
    text = query.strip().lower()
    return text in SHORT_FOLLOWUPS or (
        bool(text) and len(text) <= 3 and all(char in "?!？！。…" for char in text)
    ) or (len(text) <= 16 and any(marker in text for marker in CONTEXT_FOLLOWUP_MARKERS))


def _contextual_query(query: str, context: dict) -> str:
    memory = context.get("agent_memory") or {}
    previous_query = str(memory.get("last_query") or "").strip()
    if _is_short_followup(query) and previous_query:
        return f"{previous_query} {query.strip()}"
    return query


class AgentState(TypedDict, total=False):
    query: str
    intent: str
    confidence: float
    blocked: bool
    response: str
    sources: list[dict]
    tool_calls: list[dict]
    parameters: dict
    route_source: str
    selected_tool: str
    node_trace: list[dict]


def _classify(query: str, context: dict) -> tuple[str, float]:
    text = query.lower()
    if any(marker in text for marker in ("不要转人工", "不需要人工", "别转人工")):
        return "general", 0.95
    if any(marker in text for marker in ("转人工", "人工客服", "客服人员", "投诉", "赔偿", "律师")):
        return "human", 0.95
    if any(marker in text for marker in ("政策", "条件", "要求", "规则", "多久", "如何", "怎么申请")) and any(
        marker in text for marker in ("退货", "退款", "七天无理由", "工单", "报修")
    ):
        return "knowledge", 0.95
    refund_context = context.get("refund", {})
    awaiting = refund_context.get("awaiting")
    if awaiting and any(marker in text for marker in REFUND_CANCEL_MARKERS):
        return "refund", 0.99
    if awaiting in {"reason", "confirm"}:
        if any(marker in text for marker in ("查订单", "查询订单", "物流", "快递", "库存", "价格", "工单进度")):
            return _classify(query, {key: value for key, value in context.items() if key != "refund"})
        if any(marker in text for marker in CASUAL_MARKERS):
            return "general", 0.8
        return "refund", 0.95
    memory = context.get("agent_memory") or {}
    previous_intent = memory.get("last_intent")
    if ORDER_PATTERN.fullmatch(query.strip()) and previous_intent in {"order", "logistics"}:
        return str(previous_intent), 0.95
    if _is_short_followup(query) and previous_intent in {
        "knowledge",
        "product",
        "order",
        "logistics",
        "ticket",
    }:
        return str(previous_intent), 0.86
    if _is_short_followup(query) and memory.get("last_order_no"):
        return "order", 0.84
    priority_rules: list[tuple[str, tuple[str, ...]]] = [
        ("human", ("人工", "客服人员", "投诉", "赔偿", "律师")),
        ("refund", ("退款", "退货", "不想要", "七天无理由")),
        ("ticket", ("工单", "售后单", "报修")),
    ]
    for intent, keywords in priority_rules:
        if any(keyword in text for keyword in keywords):
            return intent, 0.95
    if any(marker in text for marker in TROUBLESHOOTING_MARKERS):
        return "knowledge", 0.95
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("logistics", ("物流", "快递", "到哪", "送达", "配送")),
        ("order", ("订单", "发货", "支付状态")),
        ("product", ("商品", "库存", "价格", "手机", "耳机", "键盘", "鼠标", "显示器")),
        ("knowledge", ("政策", "保修", "发票", "会员", "说明", "怎么用", "如何")),
    ]
    for intent, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return intent, 0.9
    if awaiting == "order_no":
        return ("refund", 0.99) if ORDER_PATTERN.search(query) else ("general", 0.8)
    return "general", 0.65


def run_customer_agent(db: Session, user: User, conversation: Conversation, query: str) -> dict:
    started = time.perf_counter()

    def classify_node(state: AgentState) -> AgentState:
        context = conversation.context or {}
        memory = context.get("agent_memory") or {}
        intent, confidence = _classify(state["query"], context)
        source, parameters = "rules", {}
        match = ORDER_PATTERN.search(state["query"])
        order_no = match.group(1).upper() if match else memory.get("last_order_no")
        if order_no:
            parameters["order_no"] = order_no
        pending = bool(context.get("refund")) and intent == "refund"
        unsafe = any(marker in state["query"].lower() for marker in INJECTION_MARKERS)
        grounded_followup = _is_short_followup(state["query"]) and (
            memory.get("last_intent") in {"order", "logistics", "product", "ticket"}
            or (bool(memory.get("last_order_no")) and intent in {"order", "logistics"})
        )
        if grounded_followup:
            source = "context_rules"
        if not pending and not unsafe and not grounded_followup:
            try:
                decision = llm_client.route(state["query"], {
                    key: memory[key] for key in ("last_intent", "last_query", "last_order_no") if key in memory
                })
                if decision is not None:
                    decision = RouteDecision.model_validate(decision)
                    if decision.confidence < 0.65:
                        source = "low_confidence_rules"
                    elif intent in {"refund", "human"} or decision.intent in {"refund", "human"}:
                        source = "guarded_rules"
                    elif intent == "knowledge" and decision.intent == "ticket":
                        source = "guarded_rules"
                    else:
                        intent, confidence, source = decision.intent, decision.confidence, "llm"
                        grounded = _contextual_query(state["query"], context)
                        if decision.product_keyword and decision.product_keyword in grounded:
                            parameters["product_keyword"] = decision.product_keyword
                        if decision.order_no and decision.order_no == order_no:
                            parameters["order_no"] = decision.order_no
                        if decision.ticket_no and decision.ticket_no in state["query"].upper():
                            parameters["ticket_no"] = decision.ticket_no
            except Exception:
                source = "fallback_rules"
        return {"intent": intent, "confidence": confidence, "sources": [], "tool_calls": [],
                "parameters": parameters, "route_source": source, "selected_tool": TOOLS[intent]}

    def safety_node(state: AgentState) -> AgentState:
        lowered = state["query"].lower()
        blocked = any(marker in lowered for marker in INJECTION_MARKERS) or state.get("selected_tool") != TOOLS.get(state.get("intent"))
        if blocked:
            return {"blocked": True, "response": "请求包含不安全指令，已停止处理。"}
        return {"blocked": False}

    def safety_route(state: AgentState) -> Literal["blocked", "dispatch"]:
        return "blocked" if state.get("blocked") else "dispatch"

    def dispatch_route(state: AgentState) -> str:
        return state["intent"]

    def blocked_node(state: AgentState) -> AgentState:
        return state

    def order_node(state: AgentState) -> AgentState:
        order_no = state.get("parameters", {}).get("order_no")
        if not order_no:
            return {"response": "请提供需要查询的订单编号，例如 EM20260710001。"}
        order = owned_order(db, order_no, user)
        call = {
            "name": "query_order",
            "arguments": {"order_no": order_no},
            "status": "success" if order else "not_found",
        }
        if not order:
            return {"response": "未找到该订单，或该订单不属于当前账号。", "tool_calls": [call]}
        products = "、".join(f"{item.product_name} × {item.quantity}" for item in order.items)
        payment = {"paid": "已支付", "pending": "待支付", "refunded": "已退款", "cancelled": "已取消"}.get(order.payment_status, order.payment_status)
        shipping = {"pending": "待发货", "shipped": "已发货", "delivered": "已签收"}.get(order.shipping_status, order.shipping_status)
        return {
            "response": f"订单 {order.order_no}：{products}；金额 ¥{order.total_amount}；支付状态：{payment}；发货状态：{shipping}。",
            "tool_calls": [call],
        }

    def logistics_node(state: AgentState) -> AgentState:
        order_no = state.get("parameters", {}).get("order_no")
        if not order_no:
            return {"response": "请提供订单编号，我会为你查询最新物流。"}
        order = owned_order(db, order_no, user)
        call = {"name": "query_logistics", "arguments": {"order_no": order_no}, "status": "success"}
        if not order:
            call["status"] = "not_found"
            return {"response": "未找到该订单，或该订单不属于当前账号。", "tool_calls": [call]}
        if not order.logistics:
            if order.shipping_status == "pending":
                response = f"订单 {order_no} 当前为待发货，尚未生成物流信息。系统中没有具体预计发货时间。"
            else:
                response = f"订单 {order_no} 的发货状态为 {order.shipping_status}，但暂未录入承运商和运单信息，请联系人工客服核验。"
            return {
                "response": response,
                "tool_calls": [call],
            }
        logistics = order.logistics
        eta = logistics.estimated_delivery.isoformat() if logistics.estimated_delivery else "待定"
        return {
            "response": f"{logistics.carrier} {logistics.tracking_no}，当前状态：{logistics.status}。最新进展：{logistics.latest_event}。预计送达：{eta}。",
            "tool_calls": [call],
        }

    def product_node(state: AgentState) -> AgentState:
        effective_query = _contextual_query(state["query"], conversation.context or {})
        keyword = state.get("parameters", {}).get("product_keyword") or next((term for term in PRODUCT_TERMS if term in effective_query), effective_query)
        products = product_search(db, keyword, 5)
        is_catalog_request = any(marker in effective_query for marker in PRODUCT_CATALOG_MARKERS)
        if not products and is_catalog_request:
            products = list(db.scalars(select(Product).where(Product.is_active.is_(True)).limit(5)))
        call = {
            "name": "search_products",
            "arguments": {"keyword": keyword},
            "status": "success" if products else "not_found",
        }
        if not products:
            return {
                "response": "没有找到与该描述匹配的商品。请提供商品名称、型号或 SKU，我会继续查询价格和库存。",
                "tool_calls": [call],
            }
        lines = [
            f"- {p.name}（{p.sku}）：¥{p.price}，可售库存 {max(0, p.stock - p.locked_stock)}"
            for p in products
        ]
        return {"response": "为你找到以下商品：\n" + "\n".join(lines), "tool_calls": [call]}

    def ticket_node(state: AgentState) -> AgentState:
        found = re.search(r"TK[A-Z0-9]{6,}", state["query"], re.IGNORECASE)
        if found:
            ticket_no = found.group(0).upper()
            stmt = select(ServiceTicket).where(ServiceTicket.ticket_no == ticket_no)
            if user.role == "customer":
                stmt = stmt.where(ServiceTicket.user_id == user.id)
            ticket = db.scalar(stmt)
            call = {
                "name": "query_ticket",
                "arguments": {"ticket_no": ticket_no},
                "status": "success" if ticket else "not_found",
            }
            return {
                "response": f"工单 {ticket_no} 当前状态：{ticket.status}。{ticket.result or ''}"
                if ticket
                else "未找到该工单。",
                "tool_calls": [call],
            }
        if not re.fullmatch(r"(?:请|帮我|我要|我想)?(?:(?:创建|提交|新建)(?:一个)?工单|申请报修|报修)(?:[，,:：。！!].*)?", state["query"].strip()):
            tickets = list(db.scalars(select(ServiceTicket).where(ServiceTicket.user_id == user.id).order_by(ServiceTicket.created_at.desc()).limit(5)))
            return {"response": "\n".join(f"工单 {item.ticket_no}：{item.title}，状态 {item.status}" for item in tickets) or "当前账号暂无工单。需要办理时请明确说明“创建工单”或“申请报修”。",
                    "tool_calls": [{"name": "query_ticket", "arguments": {}, "status": "success"}]}
        ticket = create_ticket(
            db,
            user,
            category="other",
            title="智能客服转售后",
            description=state["query"],
        )
        return {
            "response": f"已创建售后工单 {ticket.ticket_no}，客服会尽快处理。",
            "tool_calls": [
                {
                    "name": "create_ticket",
                    "arguments": {"ticket_no": ticket.ticket_no},
                    "status": "success",
                }
            ],
        }

    def refund_node(state: AgentState) -> AgentState:
        context = dict(conversation.context or {})
        refund_context = dict(context.get("refund") or {})
        if any(marker in state["query"].lower() for marker in REFUND_CANCEL_MARKERS):
            context.pop("refund", None)
            conversation.context = context
            return {
                "response": "好的，已取消本次退货流程。你还可以继续咨询商品、订单、物流或售后问题。"
            }
        match = ORDER_PATTERN.search(state["query"])
        order_no = match.group(1).upper() if match else refund_context.get("order_no")
        if not order_no:
            context["refund"] = {"awaiting": "order_no"}
            conversation.context = context
            return {
                "response": "可以，请先提供要退货的订单编号。",
                "tool_calls": [
                    {
                        "name": "refund_progress",
                        "arguments": {"step": 1, "total": 4, "label": "等待订单编号"},
                        "status": "waiting",
                    }
                ],
            }
        order = owned_order(db, order_no, user)
        call = {
            "name": "check_refund_eligibility",
            "arguments": {"order_no": order_no},
            "status": "success",
        }
        if not order:
            call["status"] = "not_found"
            return {"response": "未找到该订单，或该订单不属于当前账号。", "tool_calls": [call]}
        eligible, explanation = refund_eligibility(order)
        if not eligible:
            context.pop("refund", None)
            conversation.context = context
            return {"response": explanation, "tool_calls": [call]}
        existing, existing_ticket = existing_refund_with_ticket(db, user, order)
        if existing:
            context.pop("refund", None)
            conversation.context = context
            ticket_text = f"，关联工单 {existing_ticket.ticket_no}" if existing_ticket else ""
            return {
                "response": f"订单 {order_no} 已有进行中的退款申请 {existing.refund_no}{ticket_text}，本次没有重复创建。",
                "tool_calls": [
                    call,
                    {
                        "name": "duplicate_refund_guard",
                        "arguments": {"refund_no": existing.refund_no, "order_no": order_no},
                        "status": "blocked_duplicate",
                    },
                    {
                        "name": "refund_progress",
                        "arguments": {"step": 4, "total": 4, "label": "已有申请处理中"},
                        "status": "existing",
                    },
                ],
            }
        if refund_context.get("awaiting") not in {"reason", "confirm"} or (
            match and refund_context.get("order_no") != order_no
        ):
            context["refund"] = {"awaiting": "reason", "order_no": order_no}
            conversation.context = context
            return {
                "response": f"订单 {order_no} 符合申请条件。请说明退货原因和商品情况。",
                "tool_calls": [
                    call,
                    {
                        "name": "refund_progress",
                        "arguments": {
                            "step": 2,
                            "total": 4,
                            "label": "等待退货原因",
                            "order_no": order_no,
                        },
                        "status": "waiting",
                    },
                ],
            }
        if refund_context.get("awaiting") == "reason":
            reason = state["query"].strip()
            context["refund"] = {"awaiting": "confirm", "order_no": order_no, "reason": reason}
            conversation.context = context
            return {
                "response": f"请确认退款申请：\n\n- 订单：{order_no}\n- 原因：{reason}\n\n回复“确认提交”后才会创建退款单；回复“取消退货”可终止流程。",
                "tool_calls": [
                    call,
                    {
                        "name": "refund_progress",
                        "arguments": {
                            "step": 3,
                            "total": 4,
                            "label": "等待最终确认",
                            "order_no": order_no,
                        },
                        "status": "waiting_confirmation",
                    },
                ],
            }
        if not REFUND_CONFIRM_PATTERN.fullmatch(state["query"].strip()):
            return {
                "response": "为避免误操作，请明确回复“确认提交”或“取消退货”。",
                "tool_calls": [
                    {
                        "name": "refund_progress",
                        "arguments": {
                            "step": 3,
                            "total": 4,
                            "label": "等待最终确认",
                            "order_no": order_no,
                        },
                        "status": "waiting_confirmation",
                    }
                ],
            }
        reason = str(refund_context.get("reason") or "用户申请退款")
        refund, ticket, created = create_refund_with_ticket(db, user, order, reason, reason)
        context.pop("refund", None)
        conversation.context = context
        if not created:
            return {
                "response": f"订单 {order_no} 已有进行中的退款申请 {refund.refund_no}，本次没有重复创建。关联工单 {ticket.ticket_no}。",
                "tool_calls": [
                    call,
                    {
                        "name": "duplicate_refund_guard",
                        "arguments": {"refund_no": refund.refund_no},
                        "status": "blocked_duplicate",
                    },
                ],
            }
        return {
            "response": f"申请已提交。退款单号 {refund.refund_no}，售后工单 {ticket.ticket_no}。请保持商品及配件完整，后续进度可在工单页面查看。",
            "tool_calls": [
                call,
                {
                    "name": "create_refund",
                    "arguments": {"refund_no": refund.refund_no},
                    "status": "success",
                },
                {
                    "name": "create_ticket",
                    "arguments": {"ticket_no": ticket.ticket_no},
                    "status": "success",
                },
                {
                    "name": "refund_progress",
                    "arguments": {
                        "step": 4,
                        "total": 4,
                        "label": "申请已提交",
                        "order_no": order_no,
                    },
                    "status": "completed",
                },
            ],
        }

    def knowledge_node(state: AgentState) -> AgentState:
        effective_query = _contextual_query(state["query"], conversation.context or {})
        results = hybrid_search(db, effective_query, 3, user=user)
        if not results:
            return {
                "response": "知识库中暂时没有足够可靠的信息。你可以换一种问法，或请求转人工客服。"
            }
        context = "\n\n".join(f"[{index}] {item['document']}\n{item['content']}" for index, item in enumerate(results, 1))
        try:
            answer = llm_client.answer(effective_query, context)
        except Exception:
            answer = None
        cited = set(int(value) for value in re.findall(r"\[(\d+)\]", answer or ""))
        if not answer or not cited or not cited <= set(range(1, len(results) + 1)):
            answer = "根据企业知识库，相关信息如下：\n\n" + "\n\n".join(
                f"{item['snippet']} [{index}]" for index, item in enumerate(results[:2], 1)
            )
            cited = set(range(1, min(2, len(results)) + 1))
        sources = [
            {**{key: item[key] for key in ("document", "document_id", "chunk_id", "page", "section", "snippet", "score")}, "citation_id": index}
            for index, item in enumerate(results, 1) if index in cited
        ]
        return {
            "response": answer,
            "sources": sources,
            "tool_calls": [
                {
                    "name": "hybrid_retrieval",
                    "arguments": {"query": effective_query, "top_k": 3, "cited_chunks": [item["chunk_id"] for item in sources]},
                    "status": "success",
                }
            ],
        }

    def human_node(state: AgentState) -> AgentState:
        ticket = create_ticket(
            db,
            user,
            category="other",
            title="人工客服接管请求",
            description=state["query"],
            priority="high",
        )
        context = dict(conversation.context or {})
        previous_handoff = context.pop("handoff", None)
        if previous_handoff:
            context["last_handoff"] = previous_handoff
        conversation.context = context
        conversation.status = "waiting_human"
        return {
            "response": f"已进入人工客服队列，并创建工单 {ticket.ticket_no}。客服接入前，你仍可继续补充问题。",
            "tool_calls": [
                {
                    "name": "create_ticket",
                    "arguments": {"ticket_no": ticket.ticket_no},
                    "status": "success",
                },
                {
                    "name": "handoff_to_human",
                    "arguments": {"conversation_id": conversation.id},
                    "status": "success",
                },
            ],
        }

    def general_node(state: AgentState) -> AgentState:
        text = state["query"].lower()
        recent = list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.desc())
                .limit(10)
            )
        )
        recent.reverse()
        allowed = allowed_document_ids(db, user, {source.get("document_id") for message in recent for source in message.sources or []})
        history = [{"role": message.role, "content": message.content if all(source.get("document_id") in allowed for source in message.sources or []) else "该回答引用的文档已不可访问。"} for message in recent]
        try:
            answer = llm_client.chat(history)
        except Exception:
            answer = None
        if answer:
            return {"response": answer}
        if "重复" in text or "一样的话" in text:
            return {
                "response": "可以，我会避免重复固定话术，并根据你的具体问题直接回答。你现在最想了解什么？"
            }
        if any(marker in text for marker in ("你是谁", "你叫什么")):
            return {
                "response": "我是 EnterpriseMind 企业智能客服，可以协助查询商品、订单、物流和工单，也能根据企业知识库解答售后政策。"
            }
        if any(marker in text for marker in ("在吗", "你好", "您好")):
            return {"response": "在的。请告诉我你想查询订单、物流、商品，还是需要办理售后？"}
        if "谢谢" in text:
            return {"response": "不客气。如果还有订单、物流或售后问题，可以继续告诉我。"}
        return {
            "response": "你好，我可以帮助你查询商品、订单、物流和工单，也可以解答退换货与保修政策。请告诉我你需要办理什么。"
        }

    def traced(name, node):
        def execute(state):
            node_started = time.perf_counter()
            output = node(state)
            output["node_trace"] = [*state.get("node_trace", []), {
                "node": name, "latency_ms": round((time.perf_counter() - node_started) * 1000, 2),
                "status": "blocked" if output.get("blocked") else "success",
            }]
            return output
        return execute

    graph = StateGraph(AgentState)
    graph.add_node("classify", traced("classify", classify_node))
    graph.add_node("safety", traced("safety", safety_node))
    graph.add_node("blocked", traced("blocked", blocked_node))
    graph.add_node("dispatch", lambda state: state)
    for name, node in {
        "order": order_node,
        "logistics": logistics_node,
        "product": product_node,
        "ticket": ticket_node,
        "refund": refund_node,
        "knowledge": knowledge_node,
        "human": human_node,
        "general": general_node,
    }.items():
        graph.add_node(name, traced(name, node))
        graph.add_edge(name, END)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "safety")
    graph.add_conditional_edges(
        "safety", safety_route, {"blocked": "blocked", "dispatch": "dispatch"}
    )
    graph.add_edge("blocked", END)
    graph.add_conditional_edges(
        "dispatch",
        dispatch_route,
        {
            name: name
            for name in (
                "order",
                "logistics",
                "product",
                "ticket",
                "refund",
                "knowledge",
                "human",
                "general",
            )
        },
    )
    with capture_llm_usage() as usage_records:
        result = graph.compile().invoke({"query": query})
    if not result.get("blocked"):
        context = dict(conversation.context or {})
        previous_memory = context.get("agent_memory") or {}
        memory_query = (
            str(previous_memory.get("last_query") or query) if _is_short_followup(query) else query
        )
        context["agent_memory"] = {
            "last_intent": result.get("intent", "general"),
            "last_query": memory_query[:500],
            "last_order_no": result.get("parameters", {}).get("order_no") or previous_memory.get("last_order_no"),
        }
        conversation.context = context
    trace = {
        "name": "agent_route",
        "arguments": {
            "intent": result.get("intent", "general"),
            "confidence": round(float(result.get("confidence", 0.0)), 2),
            "source": result.get("route_source", "rules"),
            "tool": result.get("selected_tool"),
            "parameters": result.get("parameters", {}),
            "nodes": result.get("node_trace", []),
            "path": ["classify", "safety", result.get("intent", "general")],
        },
        "status": "blocked" if result.get("blocked") else "success",
    }
    result["tool_calls"] = [trace, *result.get("tool_calls", [])]
    prompt_tokens = sum(item.prompt_tokens for item in usage_records)
    completion_tokens = sum(item.completion_tokens for item in usage_records)
    estimated_cost_usd = sum(item.estimated_cost_usd for item in usage_records)
    result["usage"] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 8),
    }

    db.add(
        AgentRun(
            conversation_id=conversation.id,
            user_id=user.id,
            intent=result.get("intent", "general"),
            status="blocked" if result.get("blocked") else "success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            tool_calls=result.get("tool_calls", []),
        )
    )
    db.flush()
    return result
