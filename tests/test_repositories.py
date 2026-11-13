from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from src.data.models.outbox import Outbox
from src.data.models.payment import Payment
from src.data.repositories.outbox_repository import OutboxRepository
from src.data.repositories.payment_repository import PaymentRepository


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return [self.value] if self.value is not None else []


@pytest.fixture
def session() -> Mock:
    return Mock()


@pytest.mark.asyncio
async def test_payment_repository_get_by_id(session: Mock) -> None:
    payment = Payment(id=uuid4())
    session.execute = AsyncMock(return_value=ScalarResult(payment))
    repository = PaymentRepository(session)

    result = await repository.get_by_id(payment.id)

    assert result is payment
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_payment_repository_get_by_idempotency_key(session: Mock) -> None:
    payment = Payment(id=uuid4(), idempotency_key="key-1")
    session.execute = AsyncMock(return_value=ScalarResult(payment))
    repository = PaymentRepository(session)

    result = await repository.get_by_idempotency_key("key-1")

    assert result is payment
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_payment_repository_create_flushes_payment(session: Mock) -> None:
    session.flush = AsyncMock()
    payment = Payment(id=uuid4())
    repository = PaymentRepository(session)

    result = await repository.create(payment)

    assert result is payment
    session.add.assert_called_once_with(payment)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_outbox_repository_create_flushes_event(session: Mock) -> None:
    session.flush = AsyncMock()
    event = Outbox(id=uuid4(), aggregate_id=uuid4(), payload={})
    repository = OutboxRepository(session)

    result = await repository.create(event)

    assert result is event
    session.add.assert_called_once_with(event)
    session.flush.assert_awaited_once()
