import re
from uuid import uuid4

import pytest

from app.services.llm import llm_client


@pytest.fixture()
def private_document(client, admin_headers):
    base = client.post('/api/v1/knowledge/bases', json={'name': f'内部-{uuid4().hex}'}, headers=admin_headers)
    assert base.status_code == 201
    assert base.json()['visibility'] == 'internal'
    base_id = base.json()['id']
    uploaded = client.post(f'/api/v1/knowledge/bases/{base_id}/documents', headers=admin_headers,
        files={'file': ('内部保修.txt', '内部密令松鹤九号，内部保修审批资料。', 'text/plain')})
    assert uploaded.status_code == 201
    yield base_id, uploaded.json()['id']
    client.delete(f"/api/v1/knowledge/documents/{uploaded.json()['id']}", headers=admin_headers)


def test_internal_knowledge_denied_at_every_read_entry(client, customer_headers, admin_headers, private_document, monkeypatch):
    base_id, doc_id = private_document
    assert base_id not in {base['id'] for base in client.get('/api/v1/knowledge/bases', headers=customer_headers).json()}
    for path in (f'/api/v1/knowledge/bases/{base_id}/documents', f'/api/v1/knowledge/documents/{doc_id}'):
        assert client.get(path, headers=customer_headers).status_code == 404
        assert client.get(path, headers=admin_headers).status_code == 200
    assert client.get('/api/v1/knowledge/search', params={'q': '保修', 'base_id': base_id}, headers=customer_headers).status_code == 404
    found = client.get('/api/v1/knowledge/search', params={'q': '内部密令松鹤九号'}, headers=customer_headers).json()['results']
    assert doc_id not in {hit['document_id'] for hit in found}
    captured = []
    monkeypatch.setattr(llm_client, 'route', lambda *_: None)
    monkeypatch.setattr(llm_client, 'answer', lambda q, context: captured.append(context))
    endpoint = new_chat(client, customer_headers)
    client.post(endpoint, json={'content': '内部密令松鹤九号保修政策'}, headers=customer_headers)
    assert all('内部密令松鹤九号' not in context for context in captured)


def test_permission_change_and_customer_preview(client, customer_headers, admin_headers, private_document):
    base_id, doc_id = private_document
    endpoint = f'/api/v1/knowledge/bases/{base_id}/access'
    assert client.patch(endpoint, json={'visibility': 'public'}, headers=customer_headers).status_code == 403
    preview = {'q': '内部保修', 'base_id': base_id, 'public_only': True}
    assert client.get('/api/v1/knowledge/search', params=preview, headers=admin_headers).json()['results'] == []
    assert client.patch(endpoint, json={'visibility': 'public'}, headers=admin_headers).status_code == 200
    assert client.get(f'/api/v1/knowledge/documents/{doc_id}', headers=customer_headers).status_code == 200
    found = client.get('/api/v1/knowledge/search', params=preview, headers=admin_headers).json()['results']
    assert found and all(hit['document_id'] == doc_id for hit in found)
    assert all({'bm25_score', 'hashed_vector_score', 'rrf_score'} <= hit['retrieval'].keys() for hit in found)


def new_chat(client, headers):
    response = client.post('/api/v1/chat/conversations', json={'title': '交互回归'}, headers=headers)
    assert response.status_code == 201
    return f"/api/v1/chat/conversations/{response.json()['id']}/messages"


@pytest.mark.parametrize('answer', ['保修请查看[1]。', '编造引用[99]', '没有编号的回答', ''])
def test_citations_match_context_and_visible_sources(client, customer_headers, monkeypatch, answer):
    contexts = []
    monkeypatch.setattr(llm_client, 'route', lambda *_: None)
    def respond(query, context):
        contexts.append(context)
        return answer
    monkeypatch.setattr(llm_client, 'answer', respond)
    result = client.post(new_chat(client, customer_headers), json={'content': '保修政策是什么'}, headers=customer_headers).json()
    cited = {int(value) for value in re.findall(r'\[(\d+)\]', result['content'])}
    assert cited == {source['citation_id'] for source in result['sources']}
    assert cited and 99 not in cited
    for source in result['sources']:
        assert f"[{source['citation_id']}] {source['document']}" in contexts[0]
        content = client.get(f"/api/v1/knowledge/documents/{source['document_id']}", headers=customer_headers).json()
        assert any(chunk['id'] == source['chunk_id'] for chunk in content['chunks'])
    nodes = result['tool_calls'][0]['arguments']['nodes']
    assert [node['node'] for node in nodes] == ['classify', 'safety', 'knowledge']
    assert all(node['latency_ms'] >= 0 for node in nodes)


def test_revoked_sources_redacted_from_history(client, customer_headers, admin_headers, private_document, monkeypatch):
    base_id, _ = private_document
    client.patch(f'/api/v1/knowledge/bases/{base_id}/access', json={'visibility': 'public'}, headers=admin_headers)
    monkeypatch.setattr(llm_client, 'route', lambda *_: None)
    monkeypatch.setattr(llm_client, 'answer', lambda *_: None)
    endpoint = new_chat(client, customer_headers)
    result = client.post(endpoint, json={'content': '内部密令松鹤九号保修'}, headers=customer_headers).json()
    assert any(s['document'] == '内部保修.txt' for s in result['sources'])
    client.patch(f'/api/v1/knowledge/bases/{base_id}/access', json={'visibility': 'internal'}, headers=admin_headers)
    history = client.get(endpoint, headers=customer_headers).json()
    saved = next(message for message in history if message['id'] == result['id'])
    assert not saved['sources'] and '不可访问' in saved['content']
    captured = []
    monkeypatch.setattr(llm_client, 'chat', lambda history: captured.extend(history))
    client.post(endpoint, json={'content': '你好'}, headers=customer_headers)
    assert all('内部密令松鹤九号' not in item['content'] for item in captured if item['role'] == 'assistant')


@pytest.mark.parametrize('takeover', [False, True])
def test_customer_returns_to_bot_and_takeover_is_idempotent(client, customer_headers, admin_headers, monkeypatch, takeover):
    monkeypatch.setattr(llm_client, 'route', lambda *_: None)
    endpoint = new_chat(client, customer_headers)
    conversation_id = endpoint.split('/')[-2]
    client.post(endpoint, json={'content': '我要转人工客服'}, headers=customer_headers)
    if takeover:
        claim = f'/api/v1/handoffs/{conversation_id}/takeover'
        assert client.post(claim, headers=admin_headers).status_code == 200
        count = len(client.get(endpoint, headers=customer_headers).json())
        assert client.post(claim, headers=admin_headers).status_code == 200
        assert len(client.get(endpoint, headers=customer_headers).json()) == count
    result = client.post(f'/api/v1/chat/conversations/{conversation_id}/return-to-bot', headers=customer_headers)
    assert result.status_code == 200 and result.json()['status'] == 'bot'
    assert client.post(f'/api/v1/handoffs/{conversation_id}/messages', json={'content': '旧客服回复'}, headers=admin_headers).status_code == 404
    assert client.post(endpoint, json={'content': '查询订单 EM20260710001'}, headers=customer_headers).json()['intent'] == 'order'
