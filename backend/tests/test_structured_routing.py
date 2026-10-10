import json

import pytest
from pydantic import ValidationError

from app.agents.customer_service import _classify
from app.agents.routing import TOOLS, RouteDecision
from app.services.llm import llm_client
from app.services.runtime_config import LLMRuntimeConfig


def decision(intent, **params):
    return {"intent": intent, "tool": TOOLS[intent], "confidence": 0.95, **params}


@pytest.mark.parametrize("changes", [
    {"tool": "delete_database"}, {"tool": "query_logistics"},
    {"user_id": "other"}, {"confidence": 2}, {"order_no": "fabricated"},
])
def test_rejects_invalid_tool_and_parameters(changes):
    with pytest.raises(ValidationError):
        RouteDecision.model_validate({**decision("order"), **changes})


def test_llm_route_parses_strict_json(monkeypatch):
    config = LLMRuntimeConfig(base_url="https://example.test/v1", api_key="fake", model="fake", enabled=True, source="test")
    monkeypatch.setattr("app.services.llm.get_runtime_llm_config", lambda: config)
    monkeypatch.setattr(llm_client, "_complete", lambda *_: json.dumps(decision("logistics", order_no="EM20260710001")))
    assert llm_client.route("查询物流 EM20260710001", {}).tool == "query_logistics"
    monkeypatch.setattr(llm_client, "_complete", lambda *_: "not json")
    with pytest.raises(ValidationError):
        llm_client.route("你好", {})


@pytest.mark.parametrize("query,intent", [
    ("七天无理由退货有什么要求？", "knowledge"), ("退款多久到账", "knowledge"),
    ("如何申请工单", "knowledge"), ("我要转人工客服", "human"),
    ("查看物流", "logistics"),
])
def test_policy_and_unrelated_queries_escape_refund(query, intent):
    assert _classify(query, {"refund": {"awaiting": "confirm"}})[0] == intent


def conversation_endpoint(client, headers):
    result = client.post("/api/v1/chat/conversations", json={"title": "路由回归"}, headers=headers)
    assert result.status_code == 201
    return f"/api/v1/chat/conversations/{result.json()['id']}/messages"


def test_model_selects_logistics_with_grounded_order(client, customer_headers, monkeypatch):
    monkeypatch.setattr(llm_client, "route", lambda *_: decision("logistics", order_no="EM20999999999"))
    endpoint = conversation_endpoint(client, customer_headers)
    for query in ("帮我看看 EM20260710001 到哪了", "到哪了？"):
        result = client.post(endpoint, json={"content": query}, headers=customer_headers).json()
        assert result["intent"] == "logistics"
        route = result["tool_calls"][0]["arguments"]
        assert route["source"] == "llm"
        assert route["parameters"]["order_no"] == "EM20260710001"
        assert any(call["name"] == "query_logistics" and call["status"] == "success" for call in result["tool_calls"])


@pytest.mark.parametrize("mode", ["invalid", "timeout", "low"])
def test_model_failure_falls_back(client, customer_headers, monkeypatch, mode):
    def route(*_):
        if mode == "timeout":
            raise TimeoutError()
        return decision("order", tool="unknown") if mode == "invalid" else decision("general", confidence=0.1)
    monkeypatch.setattr(llm_client, "route", route)
    endpoint = conversation_endpoint(client, customer_headers)
    result = client.post(endpoint, json={"content": "查询订单 EM20260710001"}, headers=customer_headers).json()
    assert result["intent"] == "order"
    assert result["tool_calls"][0]["arguments"]["source"] in {"fallback_rules", "low_confidence_rules"}


@pytest.mark.parametrize("intent", ["refund", "human", "ticket"])
def test_model_cannot_authorize_writes(client, customer_headers, monkeypatch, intent):
    monkeypatch.setattr(llm_client, "route", lambda *_: decision(intent))
    monkeypatch.setattr(llm_client, "chat", lambda *_: None)
    endpoint = conversation_endpoint(client, customer_headers)
    result = client.post(endpoint, json={"content": "你好"}, headers=customer_headers).json()
    assert not any(call["name"] in {"create_ticket", "create_refund", "handoff_to_human"} for call in result["tool_calls"])


def test_ticket_query_does_not_create_ticket(client, customer_headers, monkeypatch):
    monkeypatch.setattr(llm_client, "route", lambda *_: None)
    endpoint = conversation_endpoint(client, customer_headers)
    for query in ("我的工单进度", "不要创建工单"):
        result = client.post(endpoint, json={"content": query}, headers=customer_headers).json()
        assert any(call["name"] == "query_ticket" for call in result["tool_calls"])
        assert not any(call["name"] == "create_ticket" for call in result["tool_calls"])
