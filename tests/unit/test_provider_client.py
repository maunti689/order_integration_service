import httpx
import pytest

from app.core.config import Settings
from app.integrations.provider import (
    PermanentProviderError,
    ProviderClient,
    TransientProviderError,
)


def settings():
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        provider_base_url="http://provider.test",
        provider_api_key="provider-key",
    )


def response(status_code, payload):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "http://provider.test/orders"),
    )


def test_provider_success(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response(202, {"ok": True}))
    result = ProviderClient(settings()).submit_order({}, "key", "correlation")
    assert result.status_code == 202
    assert result.payload == {"ok": True}


@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
def test_temporary_statuses_are_retryable(monkeypatch, status_code):
    monkeypatch.setattr(
        httpx, "post", lambda *args, **kwargs: response(status_code, {"temporary": True})
    )
    with pytest.raises(TransientProviderError):
        ProviderClient(settings()).submit_order({}, "key", "correlation")


def test_business_4xx_is_permanent(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda *args, **kwargs: response(400, {"reason": "bad order"})
    )
    with pytest.raises(PermanentProviderError):
        ProviderClient(settings()).submit_order({}, "key", "correlation")


def test_timeout_is_retryable(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(httpx, "post", raise_timeout)
    with pytest.raises(TransientProviderError):
        ProviderClient(settings()).submit_order({}, "key", "correlation")
