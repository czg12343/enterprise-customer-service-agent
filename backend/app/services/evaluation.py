from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.customer_service import run_customer_agent
from app.models import AgentRun, Conversation, EvaluationRun, Message, User


@dataclass(frozen=True)
class EvaluationCase:
    key: str
    name: str
    query: str
    expected_intent: str
    expected_keywords: tuple[str, ...]
    expected_tools: tuple[str, ...]
    accepted_sources: tuple[str, ...] = ()


EVALUATION_CASES = (
    EvaluationCase(
        key="order_lookup",
        name="订单查询与权限工具",
        query="查询订单 EM20260710001",
        expected_intent="order",
        expected_keywords=("EM20260710001", "4698"),
        expected_tools=("query_order",),
    ),
    EvaluationCase(
        key="logistics_lookup",
        name="物流节点查询",
        query="订单 EM20260710001 的物流到哪里了？",
        expected_intent="logistics",
        expected_keywords=("顺丰", "上海分拨中心"),
        expected_tools=("query_logistics",),
    ),
    EvaluationCase(
        key="product_lookup",
        name="商品价格与库存",
        query="显示器价格和库存是多少？",
        expected_intent="product",
        expected_keywords=("视界 27P", "1699"),
        expected_tools=("search_products",),
    ),
    EvaluationCase(
        key="warranty_rag",
        name="保修政策 RAG",
        query="保修政策是什么？",
        expected_intent="knowledge",
        expected_keywords=("一年", "保修"),
        expected_tools=("hybrid_retrieval",),
        accepted_sources=("交易配送与售后政策.md", "售后服务政策.md"),
    ),
    EvaluationCase(
        key="invoice_rag",
        name="电子发票 RAG",
        query="电子发票需要填写哪些信息？",
        expected_intent="knowledge",
        expected_keywords=("企业名称", "纳税人识别号"),
        expected_tools=("hybrid_retrieval",),
        accepted_sources=("交易配送与售后政策.md", "售后服务政策.md"),
    ),
    EvaluationCase(
        key="service_rules_rag",
        name="客服规范 RAG",
        query="请说明客服服务原则和禁止行为",
        expected_intent="knowledge",
        expected_keywords=("准确", "不得"),
        expected_tools=("hybrid_retrieval",),
        accepted_sources=("客服服务规范.md",),
    ),
)


def user_satisfaction(db: Session) -> tuple[float | None, int, int]:
    positive = db.scalar(
        select(func.count()).select_from(Message).where(Message.feedback == 1)
    ) or 0
    negative = db.scalar(
        select(func.count()).select_from(Message).where(Message.feedback == -1)
    ) or 0
    total = positive + negative
    score = round(positive / total * 100, 2) if total else None
    return score, positive, negative


def _keyword_score(answer: str, keywords: tuple[str, ...]) -> float:
    if not keywords:
        return 1.0
    normalized = answer.lower()
    return sum(keyword.lower() in normalized for keyword in keywords) / len(keywords)


def _citation_score(sources: list[dict], accepted_sources: tuple[str, ...]) -> float | None:
    if not accepted_sources:
        return None
    returned = {str(item.get("document", "")) for item in sources}
    return 1.0 if returned.intersection(accepted_sources) else 0.0


def _tool_score(tool_calls: list[dict], expected_tools: tuple[str, ...]) -> float:
    if not expected_tools:
        return 1.0
    successful = {
        str(item.get("name", ""))
        for item in tool_calls
        if item.get("status") in {"success", "completed", "existing"}
    }
    return sum(name in successful for name in expected_tools) / len(expected_tools)


def run_evaluation(db: Session, user: User) -> EvaluationRun:
    satisfaction, _, _ = user_satisfaction(db)
    evaluation = EvaluationRun(
        triggered_by=user.id,
        status="running",
        total_cases=len(EVALUATION_CASES),
        user_satisfaction=satisfaction,
        results=[],
    )
    db.add(evaluation)
    db.flush()

    case_results: list[dict] = []
    for case in EVALUATION_CASES:
        conversation = Conversation(
            user_id=user.id,
            title=f"[Evaluation] {case.name}",
            context={"evaluation": True},
        )
        db.add(conversation)
        db.flush()
        try:
            result = run_customer_agent(db, user, conversation, case.query)
            agent_run = db.scalar(
                select(AgentRun)
                .where(AgentRun.conversation_id == conversation.id)
                .order_by(AgentRun.created_at.desc())
                .limit(1)
            )
            answer = str(result.get("response", ""))
            sources = list(result.get("sources", []))
            tool_calls = list(result.get("tool_calls", []))
            intent_correct = result.get("intent") == case.expected_intent
            answer_score = _keyword_score(answer, case.expected_keywords)
            citation_score = _citation_score(sources, case.accepted_sources)
            tool_score = _tool_score(tool_calls, case.expected_tools)
            passed = bool(
                intent_correct
                and answer_score >= 0.5
                and (citation_score is None or citation_score >= 1.0)
                and tool_score >= 1.0
            )
            case_results.append(
                {
                    "key": case.key,
                    "name": case.name,
                    "query": case.query,
                    "passed": passed,
                    "actual_intent": result.get("intent", "general"),
                    "expected_intent": case.expected_intent,
                    "intent_correct": intent_correct,
                    "answer_score": round(answer_score * 100, 2),
                    "citation_score": round(citation_score * 100, 2)
                    if citation_score is not None
                    else None,
                    "tool_score": round(tool_score * 100, 2),
                    "latency_ms": agent_run.latency_ms if agent_run else 0,
                    "prompt_tokens": agent_run.prompt_tokens if agent_run else 0,
                    "completion_tokens": agent_run.completion_tokens if agent_run else 0,
                    "estimated_cost_usd": round(
                        agent_run.estimated_cost_usd if agent_run else 0.0, 8
                    ),
                    "answer": answer,
                    "sources": [item.get("document", "") for item in sources],
                    "tools": [
                        {"name": item.get("name", ""), "status": item.get("status", "")}
                        for item in tool_calls
                        if item.get("name") != "agent_route"
                    ],
                    "error": None,
                }
            )
        except Exception as exc:
            case_results.append(
                {
                    "key": case.key,
                    "name": case.name,
                    "query": case.query,
                    "passed": False,
                    "actual_intent": "error",
                    "expected_intent": case.expected_intent,
                    "intent_correct": False,
                    "answer_score": 0.0,
                    "citation_score": 0.0 if case.accepted_sources else None,
                    "tool_score": 0.0,
                    "latency_ms": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "answer": "",
                    "sources": [],
                    "tools": [],
                    "error": str(exc)[:500],
                }
            )
        finally:
            db.query(AgentRun).filter(AgentRun.conversation_id == conversation.id).delete()
            db.delete(conversation)
            db.flush()

    citation_scores = [
        float(item["citation_score"])
        for item in case_results
        if item["citation_score"] is not None
    ]
    evaluation.status = "completed"
    evaluation.passed_cases = sum(bool(item["passed"]) for item in case_results)
    evaluation.answer_accuracy = round(
        fmean(float(item["answer_score"]) for item in case_results), 2
    )
    evaluation.citation_accuracy = round(fmean(citation_scores), 2) if citation_scores else 100.0
    evaluation.tool_success_rate = round(
        fmean(float(item["tool_score"]) for item in case_results), 2
    )
    evaluation.average_latency_ms = round(
        fmean(int(item["latency_ms"]) for item in case_results), 2
    )
    evaluation.prompt_tokens = sum(int(item["prompt_tokens"]) for item in case_results)
    evaluation.completion_tokens = sum(
        int(item["completion_tokens"]) for item in case_results
    )
    evaluation.estimated_cost_usd = round(
        sum(float(item["estimated_cost_usd"]) for item in case_results), 8
    )
    evaluation.results = case_results
    db.commit()
    db.refresh(evaluation)
    return evaluation
