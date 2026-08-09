import pytest

from app.db.models import Order, OrderStatus
from app.services.exceptions import ConflictError
from app.services.state_machine import can_transition, transition_order


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderStatus.CREATED, OrderStatus.VALIDATED),
        (OrderStatus.VALIDATED, OrderStatus.SUBMITTED),
        (OrderStatus.SUBMITTED, OrderStatus.CONFIRMED),
        (OrderStatus.CONFIRMED, OrderStatus.FULFILLED),
        (OrderStatus.VALIDATED, OrderStatus.CANCELLED),
        (OrderStatus.SUBMITTED, OrderStatus.REJECTED),
    ],
)
def test_allowed_transitions(current, target):
    assert can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderStatus.FULFILLED, OrderStatus.CONFIRMED),
        (OrderStatus.REJECTED, OrderStatus.SUBMITTED),
        (OrderStatus.CANCELLED, OrderStatus.VALIDATED),
        (OrderStatus.CREATED, OrderStatus.FULFILLED),
    ],
)
def test_forbidden_transitions(current, target):
    assert not can_transition(current, target)


def test_transition_changes_order_status():
    order = Order(
        client_id="client",
        status=OrderStatus.CREATED,
        total=0,
        currency="USD",
        idempotency_key="key",
        request_hash="hash",
    )
    transition_order(order, OrderStatus.VALIDATED)
    assert order.status == OrderStatus.VALIDATED


def test_invalid_transition_raises_conflict():
    order = Order(
        client_id="client",
        status=OrderStatus.FULFILLED,
        total=0,
        currency="USD",
        idempotency_key="key",
        request_hash="hash",
    )
    with pytest.raises(ConflictError):
        transition_order(order, OrderStatus.CONFIRMED)
