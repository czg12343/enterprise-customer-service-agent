from decimal import Decimal


def test_admin_can_create_edit_and_deactivate_products(client, admin_headers, customer_headers):
    payload = {
        "sku": "qa-prod-001",
        "name": "自动化测试商品",
        "category": "测试分类",
        "description": "用于验证商品管理流程",
        "price": "199.90",
        "stock": 25,
    }
    created = client.post("/api/v1/admin/products", headers=admin_headers, json=payload)
    assert created.status_code == 201
    product = created.json()
    assert product["sku"] == "QA-PROD-001"
    assert product["is_active"] is True

    listing = client.get(
        "/api/v1/admin/products", headers=admin_headers, params={"keyword": "QA-PROD"}
    )
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [product["id"]]

    updated = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        headers=admin_headers,
        json={"price": "209.90", "stock": 18, "is_active": False},
    )
    assert updated.status_code == 200
    assert Decimal(updated.json()["price"]) == Decimal("209.90")
    assert updated.json()["stock"] == 18
    assert updated.json()["is_active"] is False

    assert client.get(
        "/api/v1/products", headers=admin_headers, params={"keyword": "QA-PROD"}
    ).json() == []
    assert client.post(
        "/api/v1/admin/products", headers=admin_headers, json=payload
    ).status_code == 409
    assert client.post(
        "/api/v1/admin/products", headers=customer_headers, json=payload
    ).status_code == 403
