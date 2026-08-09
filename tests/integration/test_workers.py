from decimal import Decimal

import pytest
from celery.exceptions import Retry

from app.db.models import Order, OrderItem, OrderStatus, OutboxEvent, Product, ProviderRequest
from app.integrations.provider import (
    PermanentProviderError,
    ProviderResult,
    TransientProviderError,
)
from app.workers import tasks


def make_validated_order(db_session):
    product = db_session.get(Product, "product-chair")
    order = Order(
        client_id="client-one",
        external_id="WORKER-ORDER-1",
        status=OrderStatus.VALIDATED,
        total=Decimal("349.00"),
        currency="USD",
        idempotency_key="worker-key-0001",
        request_hash="worker-hash",
    )
    order.items = [OrderItem(product=product, quantity=1, unit_price=product.price)]
    db_session.add(order)
    db_session.commit()
    return order.id


def test_outbox_relay_publishes_submission_task(db_session, session_factory, monkeypatch):
    order_id = make_validated_order(db_session)
    event = OutboxEvent(
        aggregate_id=order_id,
        event_type="order.submission_requested",
        payload={"order_id": order_id, "correlation_id": "relay-correlation"},
    )
    db_session.add(event)
    db_session.commit()
    sent = []

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(
        tasks.celery_app,
        "send_task",
        lambda name, args: sent.append((name, args)),
    )

    result = tasks.publish_outbox_events.run()

    assert result == {"published": 1}
    assert sent == [("app.workers.tasks.submit_order", [order_id, "relay-correlation"])]
    db_session.expire_all()
    assert db_session.get(OutboxEvent, event.id).published_at is not None


def test_worker_submits_validated_order(db_session, session_factory, monkeypatch):
    order_id = make_validated_order(db_session)

    class SuccessfulProvider:
        def submit_order(self, payload, idempotency_key, correlation_id):
            assert payload["items"][0]["sku"] == "SKU-CHAIR"
            assert idempotency_key == order_id
            return ProviderResult(202, {"provider_order_id": "provider-123"})

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "ProviderClient", lambda settings: SuccessfulProvider())

    assert tasks.submit_order.run(order_id, "correlation-123") == "submitted"
    db_session.expire_all()
    order = db_session.get(Order, order_id)
    request = db_session.query(ProviderRequest).one()
    assert order.status == OrderStatus.SUBMITTED
    assert order.provider_order_id == "provider-123"
    assert request.status == "succeeded"


def test_permanent_provider_error_rejects_without_retry(db_session, session_factory, monkeypatch):
    order_id = make_validated_order(db_session)

    class RejectingProvider:
        def submit_order(self, payload, idempotency_key, correlation_id):
            raise PermanentProviderError("bad order", 400, {"reason": "invalid"})

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "ProviderClient", lambda settings: RejectingProvider())

    assert tasks.submit_order.run(order_id, "correlation-400") == "rejected"
    db_session.expire_all()
    assert db_session.get(Order, order_id).status == OrderStatus.REJECTED
    assert db_session.query(ProviderRequest).one().status == "permanent_failure"


def test_temporary_provider_error_schedules_retry(db_session, session_factory, monkeypatch):
    order_id = make_validated_order(db_session)

    class TemporaryFailureProvider:
        def submit_order(self, payload, idempotency_key, correlation_id):
            raise TransientProviderError("temporary outage", 503, {"retry": True})

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "ProviderClient", lambda settings: TemporaryFailureProvider())

    with pytest.raises(Retry):
        tasks.submit_order.apply(args=[order_id, "correlation-503"], throw=True)
    db_session.expire_all()
    assert db_session.get(Order, order_id).status == OrderStatus.VALIDATED
    request = db_session.query(ProviderRequest).one()
    assert request.status == "temporary_failure"
    assert request.response_code == 503


def test_retry_exhaustion_marks_order_failed(db_session, session_factory, monkeypatch):
    order_id = make_validated_order(db_session)

    class UnavailableProvider:
        def submit_order(self, payload, idempotency_key, correlation_id):
            raise TransientProviderError("provider unavailable", 503)

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "ProviderClient", lambda settings: UnavailableProvider())

    result = tasks.submit_order.apply(
        args=[order_id, "correlation-exhausted"],
        throw=True,
        retries=tasks.settings.provider_max_retries,
    )
    assert result.result == "failed"
    db_session.expire_all()
    assert db_session.get(Order, order_id).status == OrderStatus.FAILED


def test_worker_ignores_order_already_processed(db_session, session_factory, monkeypatch):
    order_id = make_validated_order(db_session)
    order = db_session.get(Order, order_id)
    order.status = OrderStatus.SUBMITTED
    db_session.commit()
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)

    assert tasks.submit_order.run(order_id, "correlation-repeat") == "ignored_submitted"
    assert db_session.query(ProviderRequest).count() == 0
