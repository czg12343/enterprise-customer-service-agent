from uuid import uuid4


def _product(client, headers, sku=None):
    params = {"keyword": sku} if sku else {}
    return client.get("/api/v1/products", headers=headers, params=params).json()[0]


def _create_order(client, headers, product, payment_status="pending"):
    number = f"EM{uuid4().int}"[:32]
    response = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "customer_username": "customer",
            "order_no": number,
            "payment_status": payment_status,
            "items": [{"product_id": product["id"], "quantity": 1}],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["customer_username"] == "customer"
    return response.json()


def test_pending_order_can_be_paid_or_cancelled_with_inventory_release(client, admin_headers):
    product = _product(client, admin_headers)
    original_stock = product["stock"]
    original_locked = product["locked_stock"]

    paid_order = _create_order(client, admin_headers, product)
    reserved = _product(client, admin_headers, product["sku"])
    assert reserved["stock"] == original_stock
    assert reserved["locked_stock"] == original_locked + 1
    paid = client.post(f"/api/v1/orders/{paid_order['order_no']}/pay", headers=admin_headers)
    assert paid.status_code == 200
    assert paid.json()["payment_status"] == "paid"
    after_payment = _product(client, admin_headers, product["sku"])
    assert after_payment["stock"] == original_stock - 1
    assert after_payment["locked_stock"] == original_locked

    cancelled_order = _create_order(client, admin_headers, after_payment)
    cancelled = client.post(
        f"/api/v1/orders/{cancelled_order['order_no']}/cancel", headers=admin_headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    after_cancel = _product(client, admin_headers, product["sku"])
    assert after_cancel["stock"] == original_stock - 1
    assert after_cancel["locked_stock"] == original_locked


def test_completed_refund_restores_stock_once(client, admin_headers, customer_headers):
    product = _product(client, admin_headers)
    before = product["stock"]
    order = _create_order(client, admin_headers, product, payment_status="paid")
    assert _product(client, admin_headers, product["sku"])["stock"] == before - 1

    conversation = client.post(
        "/api/v1/chat/conversations", headers=customer_headers, json={"title": "库存恢复测试"}
    ).json()
    endpoint = f"/api/v1/chat/conversations/{conversation['id']}/messages"
    for content in (f"我要退货 {order['order_no']}", "商品不符合预期", "确认提交"):
        response = client.post(endpoint, headers=customer_headers, json={"content": content})
        assert response.status_code == 200, response.text

    tickets = client.get("/api/v1/tickets", headers=admin_headers).json()
    ticket = next(item for item in tickets if item["order_no"] == order["order_no"] and item["category"] == "refund")
    completed = client.post(
        f"/api/v1/tickets/{ticket['id']}/refund-decision",
        headers=admin_headers,
        json={"action": "complete", "result": "审核通过并完成退款"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "resolved"
    assert _product(client, admin_headers, product["sku"])["stock"] == before
    repeated = client.post(
        f"/api/v1/tickets/{ticket['id']}/refund-decision",
        headers=admin_headers,
        json={"action": "complete"},
    )
    assert repeated.status_code == 200
    assert _product(client, admin_headers, product["sku"])["stock"] == before
