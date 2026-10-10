from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import AgentRun, Conversation, DocumentChunk, Message
from app.agents.routing import RouteDecision
from app.services.llm import llm_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    readiness = client.get("/health/ready")
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ok", "database": "ok"}


def test_request_validation_rejects_invalid_business_values(
    client, customer_headers, admin_headers
):
    too_long_title = client.post(
        "/api/v1/chat/conversations",
        json={"title": "x" * 121},
        headers=customer_headers,
    )
    assert too_long_title.status_code == 422

    tickets = client.get("/api/v1/tickets", headers=admin_headers).json()
    invalid_status = client.patch(
        f"/api/v1/tickets/{tickets[0]['id']}",
        json={"status": "not-a-real-status"},
        headers=admin_headers,
    )
    assert invalid_status.status_code == 422

    customer = client.get("/api/v1/auth/me", headers=customer_headers).json()
    invalid_assignee = client.patch(
        f"/api/v1/tickets/{tickets[0]['id']}",
        json={"assignee_id": customer["id"]},
        headers=admin_headers,
    )
    assert invalid_assignee.status_code == 422


def test_customer_can_only_get_owned_order(client, customer_headers):
    response = client.get("/api/v1/orders/EM20260710001", headers=customer_headers)
    assert response.status_code == 200
    assert response.json()["logistics"]["carrier"] == "顺丰速运"

    response = client.get("/api/v1/orders/NOT-MINE", headers=customer_headers)
    assert response.status_code == 404


def test_admin_endpoint_is_role_protected(client, customer_headers, admin_headers):
    assert client.get("/api/v1/admin/stats", headers=customer_headers).status_code == 403
    response = client.get("/api/v1/admin/stats", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["users"] == 3


def test_admin_can_manage_llm_config_without_exposing_secret(
    client, customer_headers, admin_headers, monkeypatch
):
    assert client.get("/api/v1/admin/llm-config", headers=customer_headers).status_code == 403

    saved = client.put(
        "/api/v1/admin/llm-config",
        headers=admin_headers,
        json={
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "test-secret-key-not-for-production",
            "model": "openrouter/free",
            "enabled": True,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["ready"] is True
    assert saved.json()["has_api_key"] is True
    assert "api_key" not in saved.json()
    stored_config = settings.runtime_config_path.read_text(encoding="utf-8")
    assert "test-secret-key-not-for-production" not in stored_config
    assert json.loads(stored_config)["api_key_encrypted"]

    loaded = client.get("/api/v1/admin/llm-config", headers=admin_headers)
    assert loaded.json()["has_api_key"] is True
    assert "api_key" not in loaded.json()

    monkeypatch.setattr("app.api.admin.llm_client.test_connection", lambda: "连接成功")
    tested = client.post("/api/v1/admin/llm-config/test", headers=admin_headers)
    assert tested.status_code == 200
    assert tested.json() == {"success": True, "message": "连接成功"}

    disabled = client.put(
        "/api/v1/admin/llm-config",
        headers=admin_headers,
        json={
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openrouter/free",
            "enabled": False,
        },
    )
    assert disabled.status_code == 200
    assert disabled.json()["ready"] is False


def test_evaluation_center_runs_real_agent_regression_cases(
    client, customer_headers, admin_headers
):
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"title": "满意度评测"},
        headers=customer_headers,
    ).json()
    message = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        json={"content": "你好"},
        headers=customer_headers,
    ).json()
    feedback = client.post(
        f"/api/v1/chat/messages/{message['id']}/feedback",
        json={"value": 1},
        headers=customer_headers,
    )
    assert feedback.status_code == 200

    response = client.post("/api/v1/evaluations/run", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["total_cases"] == 6
    assert body["passed_cases"] >= 5
    assert body["answer_accuracy"] >= 80
    assert body["citation_accuracy"] == 100
    assert body["tool_success_rate"] == 100
    assert body["average_latency_ms"] >= 0
    assert body["prompt_tokens"] == 0
    assert body["completion_tokens"] == 0
    assert body["estimated_cost_usd"] == 0
    assert len(body["results"]) == 6
    assert all("answer_score" in item for item in body["results"])

    overview = client.get("/api/v1/evaluations", headers=admin_headers)
    assert overview.status_code == 200
    assert overview.json()["latest"]["id"] == body["id"]
    assert overview.json()["positive_feedback"] >= 1
    assert overview.json()["user_satisfaction"] == 100


def test_agent_queries_order_and_records_tool_trace(client, customer_headers):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "订单测试"}, headers=customer_headers
    ).json()
    response = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        json={"content": "查询订单 EM20260710001"},
        headers=customer_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "order"
    assert "4698" in body["content"]
    assert body["tool_calls"][0]["name"] == "agent_route"
    assert body["tool_calls"][0]["arguments"]["intent"] == "order"
    assert any(call["name"] == "query_order" for call in body["tool_calls"])


def test_vague_logistics_followups_keep_using_live_order_data(
    client, customer_headers, admin_headers, monkeypatch
):
    product = client.get("/api/v1/products", headers=admin_headers).json()[0]
    order_no = "EM864234234234"
    created = client.post(
        "/api/v1/orders",
        headers=admin_headers,
        json={
            "customer_username": "customer",
            "order_no": order_no,
            "payment_status": "paid",
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert created.status_code == 201, created.text

    def misleading_route(query, memory):
        if "怎么会" in query:
            return RouteDecision(intent="general", tool="chat", confidence=0.99)
        return None

    monkeypatch.setattr(llm_client, "route", misleading_route)
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "多轮物流同步"}, headers=customer_headers
    ).json()
    endpoint = f"/api/v1/chat/conversations/{conversation['id']}/messages"
    replies = []
    for content in (f"查询物流 {order_no}", "还没发货吗？", "怎么会这样啊？"):
        response = client.post(endpoint, json={"content": content}, headers=customer_headers)
        assert response.status_code == 200, response.text
        replies.append(response.json())

    assert all(reply["intent"] == "logistics" for reply in replies)
    assert all(any(call["name"] == "query_logistics" for call in reply["tool_calls"]) for reply in replies)
    assert all("待发货" in reply["content"] and "没有具体预计发货时间" in reply["content"] for reply in replies)
    assert all("1 小时" not in reply["content"] for reply in replies)

    identity = client.post(endpoint, json={"content": "你是谁？"}, headers=customer_headers)
    assert identity.json()["intent"] == "general"
    recovered = client.post(endpoint, json={"content": "怎么会这样啊？"}, headers=customer_headers)
    assert recovered.json()["intent"] == "order"
    assert any(call["name"] == "query_order" for call in recovered.json()["tool_calls"])
    assert "待发货" in recovered.json()["content"]
    assert "1 小时" not in recovered.json()["content"]


def test_repair_ticket_can_wait_for_customer(client, customer_headers, admin_headers):
    created = client.post(
        "/api/v1/tickets",
        json={"category": "repair", "title": "耳机维修", "description": "左侧耳机没有声音"},
        headers=customer_headers,
    )
    assert created.status_code == 201
    ticket = created.json()
    assert ticket["category"] == "repair"
    updated = client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        json={"status": "waiting_customer"},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "waiting_customer"


def test_refund_flow_collects_missing_fields(client, customer_headers):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "退款测试"}, headers=customer_headers
    ).json()
    endpoint = f"/api/v1/chat/conversations/{conversation['id']}/messages"
    first = client.post(endpoint, json={"content": "我要退货"}, headers=customer_headers)
    assert "订单编号" in first.json()["content"]
    second = client.post(endpoint, json={"content": "EM20260710001"}, headers=customer_headers)
    assert "退货原因" in second.json()["content"]
    third = client.post(endpoint, json={"content": "耳机有明显杂音"}, headers=customer_headers)
    assert third.status_code == 200
    assert "确认提交" in third.json()["content"]
    fourth = client.post(endpoint, json={"content": "确认提交"}, headers=customer_headers)
    assert "退款单号" in fourth.json()["content"]
    assert any(call["name"] == "refund_progress" for call in fourth.json()["tool_calls"])

    duplicate_conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "重复退款保护"}, headers=customer_headers
    ).json()
    duplicate_endpoint = f"/api/v1/chat/conversations/{duplicate_conversation['id']}/messages"
    client.post(duplicate_endpoint, json={"content": "我要退货"}, headers=customer_headers)
    duplicate = client.post(
        duplicate_endpoint, json={"content": "EM20260710001"}, headers=customer_headers
    )
    assert "没有重复创建" in duplicate.json()["content"]
    assert any(call["name"] == "duplicate_refund_guard" for call in duplicate.json()["tool_calls"])


def test_refund_flow_does_not_hijack_unrelated_conversation(client, customer_headers):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "退货与闲聊"}, headers=customer_headers
    ).json()
    endpoint = f"/api/v1/chat/conversations/{conversation['id']}/messages"

    started = client.post(endpoint, json={"content": "我要退货"}, headers=customer_headers)
    assert "订单编号" in started.json()["content"]

    identity = client.post(endpoint, json={"content": "你是谁？"}, headers=customer_headers)
    assert identity.json()["intent"] == "general"
    assert "EnterpriseMind" in identity.json()["content"]

    resumed = client.post(endpoint, json={"content": "EM20260710001"}, headers=customer_headers)
    assert resumed.json()["intent"] == "refund"
    assert any(text in resumed.json()["content"] for text in ("退货原因", "已有进行中的退款申请"))


def test_refund_flow_can_be_cancelled(client, customer_headers):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "取消退货"}, headers=customer_headers
    ).json()
    endpoint = f"/api/v1/chat/conversations/{conversation['id']}/messages"
    client.post(endpoint, json={"content": "我要退货"}, headers=customer_headers)

    cancelled = client.post(endpoint, json={"content": "算了，不退了"}, headers=customer_headers)

    assert cancelled.json()["intent"] == "refund"
    assert "已取消" in cancelled.json()["content"]


def test_human_handoff_takeover_reply_and_return_to_bot(client, customer_headers, admin_headers):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "人工接管闭环"}, headers=customer_headers
    ).json()
    endpoint = f"/api/v1/chat/conversations/{conversation['id']}/messages"

    requested = client.post(endpoint, json={"content": "我要转人工客服"}, headers=customer_headers)
    assert requested.status_code == 200
    assert "人工客服队列" in requested.json()["content"]

    queue = client.get("/api/v1/handoffs", headers=admin_headers)
    assert queue.status_code == 200
    assert any(item["id"] == conversation["id"] for item in queue.json())

    takeover = client.post(f"/api/v1/handoffs/{conversation['id']}/takeover", headers=admin_headers)
    assert takeover.status_code == 200
    assert takeover.json()["status"] == "human_active"

    reply = client.post(
        f"/api/v1/handoffs/{conversation['id']}/messages",
        json={"content": "您好，我是人工客服，正在为您核实。"},
        headers=admin_headers,
    )
    assert reply.status_code == 200

    history = client.get(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        headers=customer_headers,
    ).json()
    assert any("正在为您核实" in message["content"] for message in history)

    closed = client.post(f"/api/v1/handoffs/{conversation['id']}/close", headers=admin_headers)
    assert closed.status_code == 200
    resumed = client.post(
        endpoint, json={"content": "查询订单 EM20260710001"}, headers=customer_headers
    )
    assert resumed.status_code == 200
    assert resumed.json()["intent"] == "order"


def test_general_chat_uses_configured_llm_with_recent_history(
    client, customer_headers, monkeypatch
):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "多轮闲聊"}, headers=customer_headers
    ).json()
    endpoint = f"/api/v1/chat/conversations/{conversation['id']}/messages"
    captured: list[dict[str, str]] = []

    def fake_chat(messages):
        captured.extend(messages)
        return "当然可以，而且我会结合上下文回答。"

    monkeypatch.setattr("app.agents.customer_service.llm_client.chat", fake_chat)
    response = client.post(endpoint, json={"content": "你会聊天吗？"}, headers=customer_headers)

    assert response.status_code == 200
    assert response.json()["content"] == "当然可以，而且我会结合上下文回答。"
    assert captured[-1] == {"role": "user", "content": "你会聊天吗？"}


def test_general_chat_has_non_repeating_local_fallback(client, customer_headers, monkeypatch):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "避免重复"}, headers=customer_headers
    ).json()
    monkeypatch.setattr("app.agents.customer_service.llm_client.chat", lambda _messages: None)

    response = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        json={"content": "不要重复可以吗？"},
        headers=customer_headers,
    )

    assert response.status_code == 200
    assert "避免重复" in response.json()["content"]


def test_rag_returns_citations(client, customer_headers):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "知识库测试"}, headers=customer_headers
    ).json()
    response = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        json={"content": "保修政策是什么？"},
        headers=customer_headers,
    )
    assert response.status_code == 200
    assert response.json()["intent"] == "knowledge"
    assert response.json()["sources"][0]["document"] == "交易配送与售后政策.md"


def test_device_fault_uses_troubleshooting_knowledge_and_followup_context(
    client, customer_headers, monkeypatch
):
    monkeypatch.setattr("app.agents.customer_service.llm_client.answer", lambda *_args: None)
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"title": "耳机故障排查"},
        headers=customer_headers,
    ).json()
    endpoint = f"/api/v1/chat/conversations/{conversation['id']}/messages"

    first = client.post(endpoint, json={"content": "耳机无声音"}, headers=customer_headers)

    assert first.status_code == 200
    assert first.json()["intent"] == "knowledge"
    assert first.json()["sources"][0]["document"] == "常见设备故障排查指南.md"
    assert "蓝牙" in first.json()["content"]
    assert not any(call["name"] == "search_products" for call in first.json()["tool_calls"])

    followup = client.post(endpoint, json={"content": "？"}, headers=customer_headers)

    assert followup.status_code == 200
    assert followup.json()["intent"] == "knowledge"
    assert followup.json()["sources"][0]["document"] == "常见设备故障排查指南.md"
    retrieval_call = next(
        call for call in followup.json()["tool_calls"] if call["name"] == "hybrid_retrieval"
    )
    assert "耳机无声音" in retrieval_call["arguments"]["query"]


def test_product_search_does_not_fall_back_to_unrelated_catalog(client, customer_headers):
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"title": "不存在的商品"},
        headers=customer_headers,
    ).json()
    response = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        json={"content": "某款不存在的商品 ABC-UNKNOWN 价格"},
        headers=customer_headers,
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "product"
    assert "没有找到" in response.json()["content"]
    assert "星云 X1" not in response.json()["content"]
    search_call = next(
        call for call in response.json()["tool_calls"] if call["name"] == "search_products"
    )
    assert search_call["status"] == "not_found"


def test_demo_knowledge_bases_and_document_content_are_visible(client, customer_headers):
    response = client.get("/api/v1/knowledge/bases", headers=customer_headers)

    assert response.status_code == 200
    bases = response.json()
    names = {item["name"] for item in bases}
    assert "星云科技产品与售后知识库" in names
    assert "星云科技客服运营知识库" not in names
    assert all(item["document_count"] >= 2 for item in bases)
    assert all(item["chunk_count"] >= 12 for item in bases)

    product_base = next(item for item in bases if item["name"] == "星云科技产品与售后知识库")
    documents = client.get(
        f"/api/v1/knowledge/bases/{product_base['id']}/documents",
        headers=customer_headers,
    ).json()
    policy = next(item for item in documents if item["filename"] == "交易配送与售后政策.md")
    assert any(item["filename"] == "常见设备故障排查指南.md" for item in documents)
    preview = client.get(f"/api/v1/knowledge/documents/{policy['id']}", headers=customer_headers)

    assert preview.status_code == 200
    body = preview.json()
    assert body["knowledge_base_name"] == product_base["name"]
    assert len(body["chunks"]) == policy["chunk_count"]
    assert any(chunk["section"] == "七天无理由退货" for chunk in body["chunks"])
    assert any("纳税人识别号" in chunk["content"] for chunk in body["chunks"])


def test_document_upload_persists_searchable_chunks(client, admin_headers):
    knowledge_base = client.get("/api/v1/knowledge/bases", headers=admin_headers).json()[0]

    response = client.post(
        f"/api/v1/knowledge/bases/{knowledge_base['id']}/documents",
        headers=admin_headers,
        files={"file": ("search-test.txt", "星云耳机支持七天退货，配件需要完整。", "text/plain")},
    )

    assert response.status_code == 201
    document_id = response.json()["id"]
    with SessionLocal() as db:
        indexed_chunk = db.scalar(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        assert indexed_chunk is not None
        assert "星云耳机" in indexed_chunk.content

    search = client.get(
        "/api/v1/knowledge/search", params={"q": "星云耳机退货"}, headers=admin_headers
    )
    assert search.status_code == 200
    assert any(item["document"] == "search-test.txt" for item in search.json()["results"])

    deleted = client.delete(f"/api/v1/knowledge/documents/{document_id}", headers=admin_headers)
    assert deleted.status_code == 204


def test_delete_conversation_removes_agent_runs(client, customer_headers):
    conversation = client.post(
        "/api/v1/chat/conversations", json={"title": "级联删除测试"}, headers=customer_headers
    ).json()
    client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        json={"content": "查询订单 EM20260710001"},
        headers=customer_headers,
    )

    response = client.delete(
        f"/api/v1/chat/conversations/{conversation['id']}", headers=customer_headers
    )
    assert response.status_code == 204
    with SessionLocal() as db:
        assert db.get(Conversation, conversation["id"]) is None
        remaining = db.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.conversation_id == conversation["id"])
        )
        assert remaining == 0


def test_chat_rolls_back_partial_messages_when_agent_fails(client, customer_headers, monkeypatch):
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"title": "事务回滚测试"},
        headers=customer_headers,
    ).json()

    def fail_agent(*_args, **_kwargs):
        raise RuntimeError("simulated agent failure")

    monkeypatch.setattr("app.api.chat.run_customer_agent", fail_agent)
    with pytest.raises(RuntimeError, match="simulated agent failure"):
        client.post(
            f"/api/v1/chat/conversations/{conversation['id']}/messages",
            json={"content": "这条消息不应被保存"},
            headers=customer_headers,
        )

    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation["id"])
        )
        assert count == 0
