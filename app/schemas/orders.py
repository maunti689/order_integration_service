from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import OrderStatus


class OrderItemCreate(BaseModel):
    sku: str = Field(
        min_length=1,
        max_length=80,
        examples=["SKU-CHAIR"],
        description="Артикул товара в каталоге интеграционного сервиса.",
    )
    quantity: int = Field(
        gt=0,
        le=10_000,
        examples=[2],
        description="Количество единиц товара.",
    )


class OrderCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "external_id": "SHOP-1001",
                "currency": "USD",
                "items": [
                    {"sku": "SKU-CHAIR", "quantity": 1},
                    {"sku": "SKU-LAMP", "quantity": 2},
                ],
            }
        }
    )

    external_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Идентификатор заказа в клиентской системе.",
    )
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        description="Трёхбуквенный код валюты заказа.",
    )
    items: list[OrderItemCreate] = Field(
        min_length=1,
        max_length=100,
        description="Позиции заказа.",
    )


class OrderItemResponse(BaseModel):
    sku: str
    title: str
    quantity: int
    unit_price: Decimal


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str | None
    provider_order_id: str | None
    status: OrderStatus
    total: Decimal
    currency: str
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    limit: int
    offset: int


class ProviderRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    attempt: int
    response_code: int | None
    status: str
    error: str | None
    correlation_id: str
    started_at: datetime
    finished_at: datetime | None
