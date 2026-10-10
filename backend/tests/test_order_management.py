from uuid import uuid4


def test_admin_records_order_and_updates_logistics(client, admin_headers, customer_headers):
    customers = client.get('/api/v1/admin/customers', headers=admin_headers)
    assert customers.status_code == 200
    assert any(user['username'] == 'customer' for user in customers.json())
    assert client.get('/api/v1/admin/customers', headers=customer_headers).status_code == 403
    product = client.get('/api/v1/products', headers=admin_headers).json()[0]
    original_stock = product['stock']
    original_locked_stock = product['locked_stock']
    number = f"EM{uuid4().int}"[:32]
    payload = {'customer_username': 'customer', 'order_no': number, 'items': [{'product_id': product['id'], 'quantity': 2}]}
    assert client.post('/api/v1/orders', json=payload, headers=customer_headers).status_code == 403
    created = client.post('/api/v1/orders', json=payload, headers=admin_headers)
    assert created.status_code == 201, created.text
    from decimal import Decimal
    assert Decimal(str(created.json()['total_amount'])) == Decimal(str(product['price'])) * 2
    inventory = client.get(
        '/api/v1/products', headers=admin_headers, params={'keyword': product['sku']}
    ).json()[0]
    assert inventory['stock'] == original_stock - 2
    assert inventory['locked_stock'] == original_locked_stock
    assert client.post('/api/v1/orders', json=payload, headers=admin_headers).status_code == 409
    inventory_after_duplicate = client.get(
        '/api/v1/products', headers=admin_headers, params={'keyword': product['sku']}
    ).json()[0]
    assert inventory_after_duplicate['stock'] == original_stock - 2
    endpoint = f'/api/v1/orders/{number}/logistics'
    update = {'carrier': '测试快递', 'tracking_no': f'TEST{uuid4().hex}', 'status': 'in_transit', 'latest_event': '已到达大同分拨中心'}
    assert client.put(endpoint, json=update, headers=customer_headers).status_code == 403
    assert client.put(endpoint, json=update, headers=admin_headers).status_code == 200
    detail = client.get(f'/api/v1/orders/{number}', headers=customer_headers).json()
    assert detail['logistics']['latest_event'] == update['latest_event']
    assert detail['shipping_status'] == 'shipped'
    update['status'] = 'delivered'
    delivered = client.put(endpoint, json=update, headers=admin_headers)
    assert delivered.status_code == 200
    receipt = delivered.json()['logistics']['delivered_at']
    assert receipt
    assert delivered.json()['shipping_status'] == 'delivered'
    assert client.put(endpoint, json=update, headers=admin_headers).json()['logistics']['delivered_at'] == receipt
    update['status'] = 'in_transit'
    assert client.put(endpoint, json=update, headers=admin_headers).status_code == 409


def test_order_management_validates_input(client, admin_headers):
    product = client.get('/api/v1/products', headers=admin_headers).json()[0]
    original_locked_stock = product['locked_stock']
    payload = {'customer_username': 'customer', 'payment_status': 'pending', 'items': [{'product_id': product['id'], 'quantity': 0}]}
    assert client.post('/api/v1/orders', json=payload, headers=admin_headers).status_code == 422
    payload['items'][0]['quantity'] = 1
    order = client.post('/api/v1/orders', json=payload, headers=admin_headers)
    assert order.status_code == 201
    inventory = client.get(
        '/api/v1/products', headers=admin_headers, params={'keyword': product['sku']}
    ).json()[0]
    assert inventory['locked_stock'] == original_locked_stock + 1
    update = {'carrier': '测试', 'tracking_no': uuid4().hex, 'status': 'in_transit', 'latest_event': '已发货'}
    assert client.put(f"/api/v1/orders/{order.json()['order_no']}/logistics", json=update, headers=admin_headers).status_code == 409
    payload['customer_username'] = 'admin'
    assert client.post('/api/v1/orders', json=payload, headers=admin_headers).status_code == 404
    payload['customer_username'] = 'customer'
    payload['items'][0]['quantity'] = 999
    assert client.post('/api/v1/orders', json=payload, headers=admin_headers).status_code == 409
