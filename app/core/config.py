from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Сервис интеграции заказов"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://orders:local-only-orders@postgres:5432/orders"
    celery_broker_url: str = "amqp://orders:local-only-orders@rabbitmq:5672//"
    celery_result_backend: str = "redis://redis:6379/0"
    provider_base_url: str = "http://provider-mock:8081"
    provider_api_key: str = "local-only-provider-key"
    provider_webhook_secret: str = "local-only-webhook-secret"
    provider_timeout_seconds: float = 5.0
    provider_max_retries: int = 4
    api_key_salt: str = "local-only-api-key-salt"
    admin_api_key: str = "local-only-admin-key"
    outbox_batch_size: int = Field(default=50, ge=1, le=500)


@lru_cache
def get_settings() -> Settings:
    return Settings()
