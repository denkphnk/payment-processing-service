import uuid
from decimal import Decimal
from typing import Self
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from src.data.models.payment import Payment
from src.domain.schemas.payment import PaymentCreate
from src.domain.services.payment_service import PaymentService
from src.messaging.broker import payments_dlq, payments_queue
from src.messaging.consumers import payment_consumer


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


class FakeHttpClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)
        self.requests: list[tuple[str, dict]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def post(self, url: str, json: dict) -> object:
        self.requests.append((url, json))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


@pytest.fixture
def payment() -> Payment:
    return Payment(
        id=uuid.uuid4(),
        amount=Decimal("100.00"),
        currency="RUB",
        description="Test payment",
        metadata_json={"order_id": "1"},
        status="succeeded",
        idempotency_key="key-1",
        webhook_url="https://example.com/webhook",
    )


@pytest.mark.asyncio
async def test_webhook_retries_with_exponential_delay_and_succeeds(
    payment: Payment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeHttpClient(
        [
            httpx.ConnectError("connection failed"),
            httpx.ReadTimeout("request timed out"),
            FakeResponse(),
        ]
    )
    retry_sleep = AsyncMock()
    monkeypatch.setattr(payment_consumer.httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(payment_consumer.asyncio, "sleep", retry_sleep)

    await payment_consumer.send_webhook(payment)

    assert len(client.requests) == 3
    assert client.requests[-1] == (
        payment.webhook_url,
        {
            "payment_id": str(payment.id),
            "status": payment.status,
        },
    )
    assert [call.args[0] for call in retry_sleep.await_args_list] == [1, 2]


@pytest.mark.asyncio
async def test_webhook_raises_after_three_failed_attempts(
    payment: Payment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeHttpClient(
        [
            httpx.ConnectError("first"),
            httpx.ConnectError("second"),
            httpx.ConnectError("third"),
        ]
    )
    monkeypatch.setattr(payment_consumer.httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(
        payment_consumer.asyncio,
        "sleep",
        AsyncMock(),
    )

    with pytest.raises(httpx.ConnectError):
        await payment_consumer.send_webhook(payment)

    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_consumer_acks_duplicate_without_sending_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = type(
        "Session",
        (),
        {
            "execute": AsyncMock(
                return_value=type("Result", (), {"rowcount": 0})()
            ),
            "commit": AsyncMock(),
        },
    )()
    monkeypatch.setattr(
        payment_consumer,
        "async_session_factory",
        lambda: SessionContext(session),
    )
    monkeypatch.setattr(
        payment_consumer.asyncio,
        "sleep",
        AsyncMock(),
    )
    send_webhook = AsyncMock()
    monkeypatch.setattr(payment_consumer, "send_webhook", send_webhook)

    await payment_consumer.process_payment({"payment_id": str(uuid.uuid4())})

    session.commit.assert_awaited_once()
    send_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumer_sends_webhook_after_status_update(
    payment: Payment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = type(
        "Session",
        (),
        {
            "execute": AsyncMock(
                return_value=type("Result", (), {"rowcount": 1})()
            ),
            "commit": AsyncMock(),
            "scalar": AsyncMock(return_value=payment),
        },
    )()
    monkeypatch.setattr(
        payment_consumer,
        "async_session_factory",
        lambda: SessionContext(session),
    )
    monkeypatch.setattr(
        payment_consumer.asyncio,
        "sleep",
        AsyncMock(),
    )
    send_webhook = AsyncMock()
    monkeypatch.setattr(payment_consumer, "send_webhook", send_webhook)

    await payment_consumer.process_payment({"payment_id": str(payment.id)})

    session.commit.assert_awaited_once()
    send_webhook.assert_awaited_once_with(payment)


def test_queue_uses_quorum_delivery_limit_and_dlq() -> None:
    assert payments_queue.arguments == {
        "x-queue-type": "quorum",
        "x-delivery-limit": 3,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": payments_dlq.name,
    }


@pytest.mark.asyncio
async def test_consumer_raises_if_updated_payment_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = type(
        "Session",
        (),
        {
            "execute": AsyncMock(
                return_value=type("Result", (), {"rowcount": 1})()
            ),
            "commit": AsyncMock(),
            "scalar": AsyncMock(return_value=None),
        },
    )()
    monkeypatch.setattr(
        payment_consumer,
        "async_session_factory",
        lambda: SessionContext(session),
    )
    monkeypatch.setattr(
        payment_consumer.asyncio,
        "sleep",
        AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="could not be loaded"):
        await payment_consumer.process_payment({"payment_id": str(uuid.uuid4())})


@pytest.mark.asyncio
async def test_consumer_declares_dead_letter_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declare_queue = AsyncMock()
    monkeypatch.setattr(payment_consumer.broker, "declare_queue", declare_queue)

    await payment_consumer.declare_dead_letter_queue()

    declare_queue.assert_awaited_once_with(payments_dlq)


def payment_data(payment: Payment, amount: Decimal | None = None) -> PaymentCreate:
    return PaymentCreate(
        amount=payment.amount if amount is None else amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata_json,
        webhook_url=payment.webhook_url,
    )


def test_idempotency_accepts_same_payment_data(payment: Payment) -> None:
    PaymentService._check_idempotency(payment, payment_data(payment))


def test_idempotency_rejects_different_payment_data(payment: Payment) -> None:
    with pytest.raises(HTTPException) as context:
        PaymentService._check_idempotency(
            payment,
            payment_data(payment, amount=Decimal("101.00")),
        )

    assert context.value.status_code == 409
