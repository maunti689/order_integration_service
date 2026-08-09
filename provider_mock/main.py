import os
import uuid
from collections import defaultdict

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

app = FastAPI(
    title="Демонстрационный поставщик заказов",
    version="1.0.0",
    description="Локальная имитация внешнего API поставщика.",
)
attempts: defaultdict[str, int] = defaultdict(int)


class ProviderOrder(BaseModel):
    order_id: str
    external_id: str | None = None
    currency: str
    total: str
    items: list[dict]


@app.get("/health", summary="Проверить состояние поставщика")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/orders",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Принять заказ от интеграционного сервиса",
)
def receive_order(
    payload: ProviderOrder,
    x_provider_key: str = Header(alias="X-Provider-Key"),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, str | int]:
    if x_provider_key != os.getenv("PROVIDER_API_KEY", "local-only-provider-key"):
        raise HTTPException(status_code=401, detail="Некорректный API-ключ поставщика")

    attempts[idempotency_key] += 1
    fail_first = int(os.getenv("PROVIDER_FAIL_FIRST_ATTEMPTS", "0"))
    if attempts[idempotency_key] <= fail_first:
        raise HTTPException(status_code=503, detail="Запланированная временная ошибка")

    provider_order_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))
    return {
        "provider_order_id": provider_order_id,
        "status": "accepted",
        "attempt": attempts[idempotency_key],
    }
