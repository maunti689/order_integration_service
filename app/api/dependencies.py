import hmac

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import hash_api_key
from app.db.models import Client
from app.db.session import get_db
from app.services.exceptions import AuthenticationError


def get_current_client(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Client:
    if not x_api_key:
        raise AuthenticationError("Требуется заголовок X-API-Key")
    key_hash = hash_api_key(x_api_key, settings.api_key_salt)
    client = session.scalar(
        select(Client).where(Client.api_key_hash == key_hash, Client.is_active.is_(True))
    )
    if not client:
        raise AuthenticationError("Некорректный API-ключ")
    return client


def require_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise AuthenticationError("Некорректный административный API-ключ")
