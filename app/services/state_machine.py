from app.db.models import Order, OrderStatus
from app.services.exceptions import ConflictError

ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED: {
        OrderStatus.VALIDATED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.VALIDATED: {
        OrderStatus.SUBMITTED,
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.SUBMITTED: {
        OrderStatus.CONFIRMED,
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
    },
    OrderStatus.CONFIRMED: {OrderStatus.FULFILLED, OrderStatus.FAILED},
    OrderStatus.FULFILLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.FAILED: set(),
    OrderStatus.CANCELLED: set(),
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def transition_order(order: Order, target: OrderStatus) -> None:
    if not can_transition(order.status, target):
        raise ConflictError(
            f"Нельзя перевести заказ из {order.status.value} в {target.value}",
            {"current_status": order.status.value, "target_status": target.value},
        )
    order.status = target
