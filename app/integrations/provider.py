from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings


@dataclass
class ProviderResult:
    status_code: int
    payload: dict[str, Any]


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class TransientProviderError(ProviderError):
    pass


class PermanentProviderError(ProviderError):
    pass


class ProviderClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def submit_order(
        self, payload: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> ProviderResult:
        try:
            response = httpx.post(
                f"{self.settings.provider_base_url.rstrip('/')}/orders",
                json=payload,
                headers={
                    "X-Provider-Key": self.settings.provider_api_key,
                    "Idempotency-Key": idempotency_key,
                    "X-Correlation-ID": correlation_id,
                },
                timeout=self.settings.provider_timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransientProviderError(str(exc)) from exc

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {"raw": response.text[:1000]}

        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise TransientProviderError(
                "Поставщик вернул временную ошибку",
                response.status_code,
                response_payload,
            )
        if response.status_code >= 400:
            raise PermanentProviderError(
                "Поставщик отклонил запрос",
                response.status_code,
                response_payload,
            )
        return ProviderResult(response.status_code, response_payload)
