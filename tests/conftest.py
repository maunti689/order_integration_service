import os
from decimal import Decimal

test_database_url = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ["DATABASE_URL"] = test_database_url
os.environ["API_KEY_SALT"] = "test-salt"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["PROVIDER_WEBHOOK_SECRET"] = "test-webhook-secret"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_api_key
from app.db.base import Base
from app.db.models import Client, Product
from app.db.session import get_db
from app.main import app

engine_options = {}
if test_database_url.startswith("sqlite"):
    engine_options = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
engine = create_engine(test_database_url, **engine_options)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestingSessionLocal() as session:
        session.add_all(
            [
                Client(
                    id="client-one",
                    name="Client One",
                    api_key_hash=hash_api_key("client-one-key", "test-salt"),
                ),
                Client(
                    id="client-two",
                    name="Client Two",
                    api_key_hash=hash_api_key("client-two-key", "test-salt"),
                ),
                Product(
                    id="product-chair",
                    external_sku="SKU-CHAIR",
                    title="Chair",
                    price=Decimal("349.00"),
                    currency="USD",
                ),
                Product(
                    id="product-lamp",
                    external_sku="SKU-LAMP",
                    title="Lamp",
                    price=Decimal("79.00"),
                    currency="USD",
                ),
                Product(
                    id="product-inactive",
                    external_sku="SKU-INACTIVE",
                    title="Inactive",
                    price=Decimal("10.00"),
                    currency="USD",
                    is_active=False,
                ),
            ]
        )
        session.commit()
    yield


@pytest.fixture
def api_client() -> TestClient:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db_session() -> Session:
    with TestingSessionLocal() as session:
        yield session


@pytest.fixture
def session_factory():
    return TestingSessionLocal


@pytest.fixture
def database_dialect() -> str:
    return engine.dialect.name


@pytest.fixture
def client_headers() -> dict[str, str]:
    return {"X-API-Key": "client-one-key"}


@pytest.fixture
def order_payload() -> dict:
    return {
        "external_id": "CLIENT-ORDER-1001",
        "currency": "USD",
        "items": [
            {"sku": "SKU-CHAIR", "quantity": 2},
            {"sku": "SKU-LAMP", "quantity": 1},
        ],
    }
