from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select

from app.db.models import Client, Order, OrderStatus, WebhookEvent
from app.schemas.orders import OrderCreate
from app.schemas.webhooks import ProviderWebhook
from app.services.orders import create_order
from app.services.webhooks import process_provider_webhook

pytestmark = [pytest.mark.integration, pytest.mark.postgresql]


def require_postgresql(database_dialect):
    if database_dialect != "postgresql":
        pytest.skip("PostgreSQL concurrency semantics are required")


def test_concurrent_idempotent_create_has_one_winner(
    session_factory, database_dialect, order_payload
):
    require_postgresql(database_dialect)
    barrier = Barrier(2)

    def submit():
        with session_factory() as session:
            client = session.get(Client, "client-one")
            payload = OrderCreate.model_validate(order_payload)
            barrier.wait()
            order, created = create_order(session, client, payload, "concurrent-key-0001")
            return order.id, created

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))

    assert len({order_id for order_id, _ in results}) == 1
    assert sorted(created for _, created in results) == [False, True]
    with session_factory() as session:
        assert session.scalar(select(Order).where(Order.idempotency_key == "concurrent-key-0001"))


def test_concurrent_duplicate_webhook_is_applied_once(session_factory, database_dialect):
    require_postgresql(database_dialect)
    with session_factory() as session:
        order = Order(
            client_id="client-one",
            status=OrderStatus.SUBMITTED,
            total=0,
            currency="USD",
            idempotency_key="webhook-concurrency-key",
            request_hash="webhook-concurrency-hash",
        )
        session.add(order)
        session.commit()
        order_id = order.id

    payload = ProviderWebhook.model_validate(
        {
            "event_id": "concurrent-provider-event",
            "event_type": "order.confirmed",
            "order_id": order_id,
            "status": "confirmed",
            "occurred_at": "2026-07-31T12:00:00Z",
        }
    )
    barrier = Barrier(2)

    def deliver():
        with session_factory() as session:
            barrier.wait()
            return process_provider_webhook(session, payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: deliver(), range(2)))

    assert sorted(outcomes) == ["applied", "duplicate"]
    with session_factory() as session:
        assert session.query(WebhookEvent).count() == 1
        assert session.get(Order, order_id).status == OrderStatus.CONFIRMED
