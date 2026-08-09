from datetime import datetime, timezone
from decimal import Decimal

from app.db.models import Order, OrderStatus, ProviderRequest


def test_admin_key_is_required(api_client):
    response = api_client.get("/admin/provider-requests")
    assert response.status_code == 401


def test_admin_can_inspect_provider_attempts(api_client, db_session):
    order = Order(
        client_id="client-one",
        external_id="ADMIN-ORDER-1",
        status=OrderStatus.VALIDATED,
        total=Decimal("10.00"),
        currency="USD",
        idempotency_key="admin-key-0001",
        request_hash="admin-hash",
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(
        ProviderRequest(
            order_id=order.id,
            attempt=1,
            request_payload={"order_id": order.id},
            response_payload={"detail": "temporary"},
            response_code=503,
            status="temporary_failure",
            error="temporary failure",
            correlation_id="correlation-1",
            started_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    response = api_client.get("/admin/provider-requests", headers={"X-Admin-Key": "test-admin-key"})
    assert response.status_code == 200
    assert response.json()[0]["status"] == "temporary_failure"
