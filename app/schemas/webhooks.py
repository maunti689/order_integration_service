from datetime import datetime

from pydantic import BaseModel, Field


class ProviderWebhook(BaseModel):
    event_id: str = Field(
        min_length=1,
        max_length=120,
        description="Уникальный идентификатор события поставщика.",
    )
    event_type: str = Field(
        min_length=1,
        max_length=80,
        description="Тип события поставщика.",
    )
    order_id: str = Field(
        min_length=36,
        max_length=36,
        description="Идентификатор заказа интеграционного сервиса.",
    )
    status: str = Field(description="Новый статус заказа у поставщика.")
    occurred_at: datetime = Field(description="Время события на стороне поставщика.")


class WebhookResponse(BaseModel):
    event_id: str = Field(description="Идентификатор обработанного события.")
    outcome: str = Field(description="Технический результат обработки события.")
