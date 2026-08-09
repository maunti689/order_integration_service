from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_api_key
from app.db.models import Client, Product
from app.db.session import SessionLocal

DEMO_API_KEY = "demo-client-key"


def seed() -> None:
    settings = get_settings()
    with SessionLocal() as session:
        key_hash = hash_api_key(DEMO_API_KEY, settings.api_key_salt)
        client = session.scalar(select(Client).where(Client.api_key_hash == key_hash))
        if client:
            client.name = "Демонстрационный клиент"
        else:
            session.add(Client(name="Демонстрационный клиент", api_key_hash=key_hash))

        products = [
            ("SKU-CHAIR", "Эргономичное кресло", Decimal("349.00")),
            ("SKU-DESK", "Стол с регулировкой высоты", Decimal("699.00")),
            ("SKU-LAMP", "Настольная лампа", Decimal("79.00")),
        ]
        existing = {
            product.external_sku: product for product in session.scalars(select(Product)).all()
        }
        for sku, title, price in products:
            if sku in existing:
                existing[sku].title = title
                existing[sku].price = price
                existing[sku].currency = "USD"
                existing[sku].is_active = True
            else:
                session.add(
                    Product(
                        external_sku=sku,
                        title=title,
                        price=price,
                        currency="USD",
                    )
                )
        session.commit()
    print(f"Демонстрационные данные готовы. X-API-Key: {DEMO_API_KEY}")


if __name__ == "__main__":
    seed()
