from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Order, OrderStatus, WebhookEvent, utcnow
from app.schemas.webhooks import ProviderWebhook
from app.services.exceptions import NotFoundError
from app.services.state_machine import can_transition, transition_order

PROVIDER_STATUS_MAP = {
    "confirmed": OrderStatus.CONFIRMED,
    "fulfilled": OrderStatus.FULFILLED,
    "rejected": OrderStatus.REJECTED,
    "failed": OrderStatus.FAILED,
}


def _advance_to_provider_status(order: Order, target: OrderStatus) -> bool:
    if can_transition(order.status, target):
        transition_order(order, target)
        return True
    if order.status == OrderStatus.VALIDATED and target in {
        OrderStatus.CONFIRMED,
        OrderStatus.FULFILLED,
    }:
        transition_order(order, OrderStatus.SUBMITTED)
    if order.status == OrderStatus.SUBMITTED and target == OrderStatus.FULFILLED:
        transition_order(order, OrderStatus.CONFIRMED)
    if can_transition(order.status, target):
        transition_order(order, target)
        return True
    return False


def process_provider_webhook(session: Session, payload: ProviderWebhook) -> str:
    existing = session.scalar(
        select(WebhookEvent).where(WebhookEvent.provider_event_id == payload.event_id)
    )
    if existing:
        return "duplicate"

    event = WebhookEvent(
        provider_event_id=payload.event_id,
        event_type=payload.event_type,
        payload=payload.model_dump(mode="json"),
    )
    session.add(event)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return "duplicate"

    order = session.scalar(select(Order).where(Order.id == payload.order_id).with_for_update())
    if not order:
        session.rollback()
        raise NotFoundError("Заказ из события поставщика не найден")

    target = PROVIDER_STATUS_MAP.get(payload.status.lower())
    if not target:
        outcome = "ignored_unknown_status"
    elif order.status == target:
        outcome = "already_applied"
    elif _advance_to_provider_status(order, target):
        outcome = "applied"
    else:
        outcome = "ignored_out_of_order"

    event.outcome = outcome
    event.processed_at = utcnow()
    session.commit()
    return outcome
