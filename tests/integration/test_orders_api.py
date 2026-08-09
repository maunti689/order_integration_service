from app.db.models import OutboxEvent


def create_order(api_client, client_headers, order_payload, key="idempotency-key-0001"):
    return api_client.post(
        "/orders",
        json=order_payload,
        headers={**client_headers, "Idempotency-Key": key},
    )


def test_health_and_readiness(api_client):
    assert api_client.get("/health").json() == {"status": "ok"}
    assert api_client.get("/ready").json() == {"status": "ready"}


def test_api_key_is_required(api_client):
    response = api_client.get("/orders")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


def test_invalid_api_key_is_rejected(api_client):
    response = api_client.get("/orders", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_create_order_calculates_total_and_creates_outbox(
    api_client, client_headers, order_payload, db_session
):
    response = api_client.post(
        "/orders",
        json=order_payload,
        headers={
            **client_headers,
            "Idempotency-Key": "idempotency-key-0001",
            "X-Request-ID": "client-request-123",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "validated"
    assert response.json()["total"] == "777.00"
    assert response.headers["X-Request-ID"] == "client-request-123"
    outbox_event = db_session.query(OutboxEvent).one()
    assert outbox_event.payload["correlation_id"] == "client-request-123"


def test_duplicate_request_returns_same_order(api_client, client_headers, order_payload):
    first = create_order(api_client, client_headers, order_payload)
    second = create_order(api_client, client_headers, order_payload)
    assert second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json()["id"] == first.json()["id"]


def test_same_key_with_different_payload_conflicts(api_client, client_headers, order_payload):
    create_order(api_client, client_headers, order_payload)
    order_payload["items"][0]["quantity"] = 3
    response = create_order(api_client, client_headers, order_payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_external_order_id_is_unique_per_client(api_client, client_headers, order_payload):
    assert create_order(api_client, client_headers, order_payload).status_code == 201
    response = create_order(api_client, client_headers, order_payload, key="idempotency-key-0002")
    assert response.status_code == 409


def test_duplicate_sku_is_rejected(api_client, client_headers, order_payload):
    order_payload["items"].append({"sku": "SKU-CHAIR", "quantity": 1})
    response = create_order(api_client, client_headers, order_payload)
    assert response.status_code == 422


def test_unknown_product_is_rejected(api_client, client_headers, order_payload):
    order_payload["items"][0]["sku"] = "DOES-NOT-EXIST"
    response = create_order(api_client, client_headers, order_payload)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["skus"] == ["DOES-NOT-EXIST"]


def test_inactive_product_is_rejected(api_client, client_headers, order_payload):
    order_payload["items"] = [{"sku": "SKU-INACTIVE", "quantity": 1}]
    response = create_order(api_client, client_headers, order_payload)
    assert response.status_code == 422


def test_currency_mismatch_is_rejected(api_client, client_headers, order_payload):
    order_payload["currency"] = "EUR"
    response = create_order(api_client, client_headers, order_payload)
    assert response.status_code == 422


def test_client_cannot_read_another_clients_order(api_client, client_headers, order_payload):
    order_id = create_order(api_client, client_headers, order_payload).json()["id"]
    response = api_client.get(f"/orders/{order_id}", headers={"X-API-Key": "client-two-key"})
    assert response.status_code == 404


def test_list_orders_supports_status_filter(api_client, client_headers, order_payload):
    create_order(api_client, client_headers, order_payload)
    response = api_client.get("/orders?status=validated", headers=client_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["status"] == "validated"


def test_order_can_be_cancelled_before_submission(api_client, client_headers, order_payload):
    order_id = create_order(api_client, client_headers, order_payload).json()["id"]
    response = api_client.post(f"/orders/{order_id}/cancel", headers=client_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_terminal_order_cannot_be_cancelled_twice(api_client, client_headers, order_payload):
    order_id = create_order(api_client, client_headers, order_payload).json()["id"]
    api_client.post(f"/orders/{order_id}/cancel", headers=client_headers)
    response = api_client.post(f"/orders/{order_id}/cancel", headers=client_headers)
    assert response.status_code == 409


def test_invalid_request_uses_common_error_format(api_client, client_headers):
    response = api_client.post(
        "/orders",
        json={"items": []},
        headers={**client_headers, "Idempotency-Key": "valid-key-123"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_failed"
