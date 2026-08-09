import logging
import uuid
from datetime import datetime, timezone

from celery import Task
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import (
    Order,
    OrderItem,
    OrderStatus,
    OutboxEvent,
    ProviderRequest,
)
from app.db.session import SessionLocal
from app.integrations.provider import (
    PermanentProviderError,
    ProviderClient,
    TransientProviderError,
)
from app.services.state_machine import can_transition, transition_order
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


def _provider_payload(order: Order) -> dict:
    return {
        "order_id": order.id,
        "external_id": order.external_id,
        "currency": order.currency,
        "total": str(order.total),
        "items": [
            {
                "sku": item.product.external_sku,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
            }
            for item in order.items
        ],
    }


@celery_app.task(name="app.workers.tasks.publish_outbox_events")
def publish_outbox_events() -> dict[str, int]:
    published = 0
    with SessionLocal() as session:
        events = list(
            session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .limit(settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
            ).all()
        )
        for event in events:
            try:
                if event.event_type == "order.submission_requested":
                    celery_app.send_task(
                        "app.workers.tasks.submit_order",
                        args=[
                            event.aggregate_id,
                            event.payload.get("correlation_id", event.id),
                        ],
                    )
                event.published_at = datetime.now(timezone.utc)
                event.attempts += 1
                published += 1
            except Exception:
                event.attempts += 1
                logger.exception("Не удалось опубликовать событие outbox")
        session.commit()
    return {"published": published}


@celery_app.task(
    bind=True,
    name="app.workers.tasks.submit_order",
    max_retries=settings.provider_max_retries,
)
def submit_order(self: Task, order_id: str, correlation_id: str | None = None) -> str:
    correlation_id = correlation_id or str(uuid.uuid4())
    with SessionLocal() as session:
        order = session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items).selectinload(OrderItem.product))
            .with_for_update()
        )
        if not order:
            logger.error(
                "Заказ для передачи поставщику не найден",
                extra={"order_id": order_id},
            )
            return "not_found"
        if order.status != OrderStatus.VALIDATED:
            return f"ignored_{order.status.value}"

        attempt = (
            session.scalar(
                select(func.count(ProviderRequest.id)).where(ProviderRequest.order_id == order.id)
            )
            or 0
        ) + 1
        payload = _provider_payload(order)
        provider_request = ProviderRequest(
            order_id=order.id,
            attempt=attempt,
            request_payload=payload,
            status="pending",
            correlation_id=correlation_id,
        )
        session.add(provider_request)
        session.commit()

    client = ProviderClient(settings)
    logger.info(
        "Передача заказа поставщику",
        extra={
            "order_id": order_id,
            "attempt": attempt,
            "correlation_id": correlation_id,
        },
    )
    try:
        result = client.submit_order(payload, order_id, correlation_id)
    except TransientProviderError as exc:
        exhausted = self.request.retries >= settings.provider_max_retries
        with SessionLocal() as session:
            request = session.get(ProviderRequest, provider_request.id)
            request.status = "temporary_failure"
            request.response_code = exc.status_code
            request.response_payload = exc.payload
            request.error = str(exc)
            request.finished_at = datetime.now(timezone.utc)
            if exhausted:
                order = session.get(Order, order_id)
                if can_transition(order.status, OrderStatus.FAILED):
                    transition_order(order, OrderStatus.FAILED)
            session.commit()
        if exhausted:
            return "failed"
        countdown = min(60, 2 ** (self.request.retries + 1))
        raise self.retry(exc=exc, countdown=countdown) from exc
    except PermanentProviderError as exc:
        with SessionLocal() as session:
            request = session.get(ProviderRequest, provider_request.id)
            order = session.get(Order, order_id)
            request.status = "permanent_failure"
            request.response_code = exc.status_code
            request.response_payload = exc.payload
            request.error = str(exc)
            request.finished_at = datetime.now(timezone.utc)
            if can_transition(order.status, OrderStatus.REJECTED):
                transition_order(order, OrderStatus.REJECTED)
            session.commit()
        return "rejected"

    with SessionLocal() as session:
        request = session.get(ProviderRequest, provider_request.id)
        order = session.get(Order, order_id)
        request.status = "succeeded"
        request.response_code = result.status_code
        request.response_payload = result.payload
        request.finished_at = datetime.now(timezone.utc)
        order.provider_order_id = result.payload.get("provider_order_id")
        if can_transition(order.status, OrderStatus.SUBMITTED):
            transition_order(order, OrderStatus.SUBMITTED)
        session.commit()
    logger.info(
        "Поставщик принял заказ",
        extra={"order_id": order_id, "attempt": attempt, "correlation_id": correlation_id},
    )
    return "submitted"
