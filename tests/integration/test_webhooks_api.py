import json
from datetime import datetime, timezone

from app.core.security import sign_webhook
from app.db.models import Order, OrderStatus, WebhookEvent


def create_order(api_client, client_headers, order_payload):
    return api_client.post(
        "/orders",
        json=order_payload,
        headers={**client_headers, "Idempotency-Key": "webhook-order-key"},
    ).json()["id"]


def webhook_payload(order_id, event_id="provider-event-1", status="confirmed"):
    return {
        "event_id": event_id,
        "event_type": f"order.{status}",
        "order_id": order_id,
        "status": status,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }


def send_webhook(api_client, payload, signature=None):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = signature or sign_webhook(raw, "test-webhook-secret")
    return api_client.post(
        "/webhooks/provider",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Provider-Signature": signature,
        },
    )


def set_status(db_session, order_id, status):
    order = db_session.get(Order, order_id)
    order.status = status
    db_session.commit()


def test_bad_webhook_signature_is_rejected(api_client):
    response = send_webhook(api_client, webhook_payload("0" * 36), signature="bad")
    assert response.status_code == 401


def test_confirmed_webhook_advances_submitted_order(
    api_client, client_headers, order_payload, db_session
):
    order_id = create_order(api_client, client_headers, order_payload)
    set_status(db_session, order_id, OrderStatus.SUBMITTED)
    response = send_webhook(api_client, webhook_payload(order_id))
    assert response.status_code == 200
    assert response.json()["outcome"] == "applied"
    db_session.expire_all()
    assert db_session.get(Order, order_id).status == OrderStatus.CONFIRMED


def test_duplicate_webhook_has_no_second_side_effect(
    api_client, client_headers, order_payload, db_session
):
    order_id = create_order(api_client, client_headers, order_payload)
    set_status(db_session, order_id, OrderStatus.SUBMITTED)
    payload = webhook_payload(order_id)
    assert send_webhook(api_client, payload).json()["outcome"] == "applied"
    assert send_webhook(api_client, payload).json()["outcome"] == "duplicate"
    assert db_session.query(WebhookEvent).count() == 1


def test_old_event_cannot_regress_fulfilled_order(
    api_client, client_headers, order_payload, db_session
):
    order_id = create_order(api_client, client_headers, order_payload)
    set_status(db_session, order_id, OrderStatus.FULFILLED)
    response = send_webhook(api_client, webhook_payload(order_id))
    assert response.json()["outcome"] == "ignored_out_of_order"
    db_session.expire_all()
    assert db_session.get(Order, order_id).status == OrderStatus.FULFILLED


def test_fulfilled_event_can_skip_missing_intermediate_webhook(
    api_client, client_headers, order_payload, db_session
):
    order_id = create_order(api_client, client_headers, order_payload)
    set_status(db_session, order_id, OrderStatus.SUBMITTED)
    response = send_webhook(
        api_client,
        webhook_payload(order_id, event_id="provider-event-fulfilled", status="fulfilled"),
    )
    assert response.json()["outcome"] == "applied"
    db_session.expire_all()
    assert db_session.get(Order, order_id).status == OrderStatus.FULFILLED


def test_unknown_provider_status_is_recorded_without_transition(
    api_client, client_headers, order_payload, db_session
):
    order_id = create_order(api_client, client_headers, order_payload)
    set_status(db_session, order_id, OrderStatus.SUBMITTED)
    response = send_webhook(
        api_client,
        webhook_payload(order_id, event_id="provider-event-unknown", status="paused"),
    )
    assert response.json()["outcome"] == "ignored_unknown_status"
    db_session.expire_all()
    assert db_session.get(Order, order_id).status == OrderStatus.SUBMITTED


def test_webhook_for_missing_order_returns_not_found(api_client):
    response = send_webhook(api_client, webhook_payload("0" * 36))
    assert response.status_code == 404


def test_malformed_signed_webhook_uses_validation_error(api_client):
    raw = b'{"event_id":"only-one-field"}'
    response = api_client.post(
        "/webhooks/provider",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Provider-Signature": sign_webhook(raw, "test-webhook-secret"),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_failed"
