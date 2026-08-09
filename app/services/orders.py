import hashlib
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Client,
    Order,
    OrderItem,
    OrderStatus,
    OutboxEvent,
    Product,
)
from app.schemas.orders import OrderCreate, OrderItemResponse, OrderResponse
from app.services.exceptions import ConflictError, DomainValidationError, NotFoundError
from app.services.state_machine import transition_order


def request_fingerprint(payload: OrderCreate) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def order_to_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        external_id=order.external_id,
        provider_order_id=order.provider_order_id,
        status=order.status,
        total=order.total,
        currency=order.currency,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            OrderItemResponse(
                sku=item.product.external_sku,
                title=item.product.title,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
            for item in order.items
        ],
    )


def _load_order(session: Session, order_id: str) -> Order | None:
    return session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
    )


def create_order(
    session: Session,
    client: Client,
    payload: OrderCreate,
    idempotency_key: str,
    correlation_id: str | None = None,
) -> tuple[Order, bool]:
    fingerprint = request_fingerprint(payload)
    existing = session.scalar(
        select(Order)
        .where(
            Order.client_id == client.id,
            Order.idempotency_key == idempotency_key,
        )
        .options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    if existing:
        if existing.request_hash != fingerprint:
            raise ConflictError("Idempotency-Key уже использован для другого запроса")
        return existing, False

    requested_skus = [item.sku for item in payload.items]
    if len(set(requested_skus)) != len(requested_skus):
        raise DomainValidationError("Один SKU может встречаться в заказе только один раз")

    products = session.scalars(
        select(Product).where(Product.external_sku.in_(requested_skus))
    ).all()
    product_by_sku = {product.external_sku: product for product in products}
    missing = sorted(set(requested_skus) - set(product_by_sku))
    if missing:
        raise DomainValidationError("Неизвестный SKU товара", {"skus": missing})

    inactive = sorted(sku for sku in requested_skus if not product_by_sku[sku].is_active)
    if inactive:
        raise DomainValidationError("Неактивный товар нельзя добавить в заказ", {"skus": inactive})

    currency = payload.currency.upper()
    wrong_currency = sorted(
        sku for sku in requested_skus if product_by_sku[sku].currency != currency
    )
    if wrong_currency:
        raise DomainValidationError(
            "Валюта заказа не совпадает с валютой товара", {"skus": wrong_currency}
        )

    total = sum(
        (product_by_sku[item.sku].price * item.quantity for item in payload.items),
        start=Decimal("0.00"),
    )
    order = Order(
        client_id=client.id,
        external_id=payload.external_id,
        status=OrderStatus.CREATED,
        total=total,
        currency=currency,
        idempotency_key=idempotency_key,
        request_hash=fingerprint,
    )
    order.items = [
        OrderItem(
            product=product_by_sku[item.sku],
            quantity=item.quantity,
            unit_price=product_by_sku[item.sku].price,
        )
        for item in payload.items
    ]
    transition_order(order, OrderStatus.VALIDATED)
    session.add(order)
    try:
        session.flush()
        session.add(
            OutboxEvent(
                aggregate_id=order.id,
                event_type="order.submission_requested",
                payload={
                    "order_id": order.id,
                    "correlation_id": correlation_id or order.id,
                },
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(Order)
            .where(
                Order.client_id == client.id,
                Order.idempotency_key == idempotency_key,
            )
            .options(selectinload(Order.items).selectinload(OrderItem.product))
        )
        if existing and existing.request_hash == fingerprint:
            return existing, False
        if existing:
            raise ConflictError("Idempotency-Key уже использован для другого запроса") from exc
        raise ConflictError("Заказ с таким внешним идентификатором уже существует") from exc
    return order, True


def get_order(session: Session, client: Client, order_id: str) -> Order:
    order = session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.client_id == client.id)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    if not order:
        raise NotFoundError("Заказ не найден")
    return order


def list_orders(
    session: Session,
    client: Client,
    status: OrderStatus | None,
    created_from: datetime | None,
    created_to: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[Order], int]:
    filters = [Order.client_id == client.id]
    if status:
        filters.append(Order.status == status)
    if created_from:
        filters.append(Order.created_at >= created_from)
    if created_to:
        filters.append(Order.created_at <= created_to)

    total = session.scalar(select(func.count(Order.id)).where(*filters)) or 0
    orders = session.scalars(
        select(Order)
        .where(*filters)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .order_by(Order.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(orders), total


def cancel_order(session: Session, client: Client, order_id: str) -> Order:
    order = session.scalar(
        select(Order)
        .where(Order.id == order_id, Order.client_id == client.id)
        .with_for_update()
        .options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    if not order:
        raise NotFoundError("Заказ не найден")
    transition_order(order, OrderStatus.CANCELLED)
    session.commit()
    return order
