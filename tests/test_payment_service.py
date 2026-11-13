from decimal import Decimal
from typing import Self
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.data.models.payment import Payment
from src.domain.schemas.payment import PaymentCreate
from src.domain.services.payment_service import PaymentService


class TransactionContext:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


def build_data() -> PaymentCreate:
    return PaymentCreate(
        amount=Decimal("100.00"),
        currency="RUB",
        description="Test payment",
        metadata={"order_id": "1"},
        webhook_url="https://example.com/webhook",
    )


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
    )


def build_service() -> tuple[PaymentService, Mock]:
    session = Mock()
    session.begin.return_value = TransactionContext()
    service = PaymentService(session)
    return service, session


@pytest.mark.asyncio
async def test_create_payment_persists_payment_and_outbox_event() -> None:
    service, _ = build_service()
    service.payment_repository.get_by_idempotency_key = AsyncMock(
        return_value=None
    )

    async def create_payment(payment: Payment) -> Payment:
        payment.id = uuid4()
        return payment

    service.payment_repository.create = AsyncMock(side_effect=create_payment)
    service.outbox_repository.create = AsyncMock()

    payment = await service.create_payment(build_data(), "key-1")

    assert payment.status == "pending"
    service.payment_repository.create.assert_awaited_once()
    event = service.outbox_repository.create.await_args.args[0]
    assert event.aggregate_id == payment.id
    assert event.event_type == "payment.created"
    assert event.payload == {"payment_id": str(payment.id)}


@pytest.mark.asyncio
async def test_create_payment_returns_existing_idempotent_payment() -> None:
    service, _ = build_service()
    existing = build_payment()
    service.payment_repository.get_by_idempotency_key = AsyncMock(
        return_value=existing
    )
    service.payment_repository.create = AsyncMock()
    service.outbox_repository.create = AsyncMock()

    result = await service.create_payment(build_data(), "key-1")

    assert result is existing
    service.payment_repository.create.assert_not_awaited()
    service.outbox_repository.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_payment_handles_concurrent_idempotency_insert() -> None:
    service, _ = build_service()
    existing = build_payment()
    service.payment_repository.get_by_idempotency_key = AsyncMock(
        side_effect=[None, existing]
    )
    service.payment_repository.create = AsyncMock(
        side_effect=IntegrityError("insert", {}, Exception("duplicate"))
    )

    result = await service.create_payment(build_data(), "key-1")

    assert result is existing


@pytest.mark.asyncio
async def test_create_payment_reraises_unknown_integrity_error() -> None:
    service, _ = build_service()
    service.payment_repository.get_by_idempotency_key = AsyncMock(
        side_effect=[None, None]
    )
    error = IntegrityError("insert", {}, Exception("database error"))
    service.payment_repository.create = AsyncMock(side_effect=error)

    with pytest.raises(IntegrityError) as context:
        await service.create_payment(build_data(), "key-1")

    assert context.value is error


@pytest.mark.asyncio
async def test_get_payment_returns_existing_payment() -> None:
    service, _ = build_service()
    payment = build_payment()
    service.payment_repository.get_by_id = AsyncMock(return_value=payment)

    result = await service.get_payment(payment.id)

    assert result is payment


@pytest.mark.asyncio
async def test_get_payment_raises_for_missing_payment() -> None:
    service, _ = build_service()
    service.payment_repository.get_by_id = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as context:
        await service.get_payment(uuid4())

    assert context.value.status_code == 404
