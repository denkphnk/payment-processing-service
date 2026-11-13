from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.api.dependencies.auth import verify_api_key
from src.api.dependencies.payment import get_payment_service
from src.api.routers.payments import router
from src.core.config import settings
from src.data.models.payment import Payment
from src.domain.services.payment_service import PaymentService


def build_payment() -> Payment:
    return Payment(
        id=uuid4(),
        amount=Decimal("100.00"),
        currency="RUB",
        description="Test payment",
        metadata_json={"order_id": "1"},
        status="pending",
        idempotency_key="key-1",
        webhook_url="https://example.com/webhook",
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def service() -> AsyncMock:
    return AsyncMock(spec=PaymentService)


@pytest.fixture
def app(service: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[get_payment_service] = lambda: service
    return app


@pytest.mark.asyncio
async def test_create_payment_returns_accepted_response(
    app: FastAPI,
    service: AsyncMock,
) -> None:
    payment = build_payment()
    service.create_payment.return_value = payment

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/payments",
            headers={"Idempotency-Key": "key-1"},
            json={
                "amount": "100.00",
                "currency": "RUB",
                "description": "Test payment",
                "metadata": {"order_id": "1"},
                "webhook_url": "https://example.com/webhook",
            },
        )

    assert response.status_code == 202
    assert response.json()["payment_id"] == str(payment.id)
    assert response.json()["status"] == "pending"
    assert response.json()["created_at"] == (
        payment.created_at.isoformat().replace("+00:00", "Z")
    )
    service.create_payment.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_payment_requires_idempotency_key(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/payments",
            json={
                "amount": "100.00",
                "currency": "RUB",
                "webhook_url": "https://example.com/webhook",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_payment_returns_details(app: FastAPI, service: AsyncMock) -> None:
    payment = build_payment()
    service.get_payment.return_value = payment

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/payments/{payment.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(payment.id)
    assert response.json()["metadata"] == payment.metadata_json


@pytest.mark.asyncio
async def test_invalid_api_key_is_rejected(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "api_key", "test-api-key")
    app.dependency_overrides.pop(verify_api_key)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/payments/{uuid4()}",
            headers={"X-API-Key": "wrong-key"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"
