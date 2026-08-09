import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_client, require_admin
from app.core.config import Settings, get_settings
from app.core.logging import request_id_context
from app.core.security import verify_webhook_signature
from app.db.models import Client, OrderStatus, ProviderRequest
from app.db.session import get_db
from app.schemas.orders import (
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    ProviderRequestResponse,
)
from app.schemas.webhooks import ProviderWebhook, WebhookResponse
from app.services.exceptions import AuthenticationError
from app.services.orders import (
    cancel_order,
    create_order,
    get_order,
    list_orders,
    order_to_response,
)
from app.services.webhooks import process_provider_webhook

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", tags=["Система"], summary="Проверить процесс приложения")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", tags=["Система"], summary="Проверить готовность базы данных")
def ready(session: Session = Depends(get_db)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Заказы"],
    summary="Создать заказ",
    description=(
        "Принимает заказ клиентской системы. Повторный запрос с тем же "
        "`Idempotency-Key` и тем же телом возвращает ранее созданный заказ."
    ),
)
def create_order_endpoint(
    payload: OrderCreate,
    response: Response,
    idempotency_key: str = Header(min_length=8, max_length=120, alias="Idempotency-Key"),
    client: Client = Depends(get_current_client),
    session: Session = Depends(get_db),
) -> OrderResponse:
    order, created = create_order(
        session,
        client,
        payload,
        idempotency_key,
        correlation_id=request_id_context.get(),
    )
    logger.info(
        "Заказ принят",
        extra={"order_id": order.id, "correlation_id": request_id_context.get()},
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return order_to_response(order)


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    tags=["Заказы"],
    summary="Получить заказ",
)
def get_order_endpoint(
    order_id: str,
    client: Client = Depends(get_current_client),
    session: Session = Depends(get_db),
) -> OrderResponse:
    return order_to_response(get_order(session, client, order_id))


@router.get(
    "/orders",
    response_model=OrderListResponse,
    tags=["Заказы"],
    summary="Получить список заказов",
)
def list_orders_endpoint(
    order_status: OrderStatus | None = Query(default=None, alias="status"),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    client: Client = Depends(get_current_client),
    session: Session = Depends(get_db),
) -> OrderListResponse:
    orders, total = list_orders(
        session, client, order_status, created_from, created_to, limit, offset
    )
    return OrderListResponse(
        items=[order_to_response(order) for order in orders],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/orders/{order_id}/cancel",
    response_model=OrderResponse,
    tags=["Заказы"],
    summary="Отменить заказ до передачи поставщику",
)
def cancel_order_endpoint(
    order_id: str,
    client: Client = Depends(get_current_client),
    session: Session = Depends(get_db),
) -> OrderResponse:
    return order_to_response(cancel_order(session, client, order_id))


@router.post(
    "/webhooks/provider",
    response_model=WebhookResponse,
    tags=["Webhook поставщика"],
    summary="Принять событие поставщика",
)
async def provider_webhook_endpoint(
    request: Request,
    x_provider_signature: str | None = Header(default=None, alias="X-Provider-Signature"),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WebhookResponse:
    raw_payload = await request.body()
    if not x_provider_signature or not verify_webhook_signature(
        raw_payload, x_provider_signature, settings.provider_webhook_secret
    ):
        raise AuthenticationError("Некорректная подпись webhook")
    try:
        payload = ProviderWebhook.model_validate_json(raw_payload)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    outcome = process_provider_webhook(session, payload)
    return WebhookResponse(event_id=payload.event_id, outcome=outcome)


@router.get(
    "/admin/provider-requests",
    response_model=list[ProviderRequestResponse],
    tags=["Администрирование"],
    summary="Посмотреть попытки передачи заказов",
    dependencies=[Depends(require_admin)],
)
def list_provider_requests_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[ProviderRequest]:
    return list(
        session.scalars(
            select(ProviderRequest).order_by(ProviderRequest.started_at.desc()).limit(limit)
        ).all()
    )
