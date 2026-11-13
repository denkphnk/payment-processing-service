from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.data.models.outbox import Outbox, OutboxStatus
from src.messaging import publisher


class SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


def build_event(attempts: int = 0) -> Outbox:
    return Outbox(
        id=uuid4(),
        aggregate_id=uuid4(),
        status=OutboxStatus.PENDING,
        event_type="payment.created",
        payload={"payment_id": str(uuid4())},
        attempts=attempts,
        next_attempt_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_get_pending_events_returns_due_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = build_event()
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [event])
            )
        )
    )
    monkeypatch.setattr(
        publisher,
        "async_session_factory",
        lambda: SessionContext(session),
    )

    result = await publisher.get_pending_events()

    assert result == [event]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_event_marks_event_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = build_event()
    session = SimpleNamespace(
        get=AsyncMock(return_value=event),
        commit=AsyncMock(),
    )
    publish = AsyncMock()
    monkeypatch.setattr(publisher.broker, "publish", publish)
    monkeypatch.setattr(
        publisher,
        "async_session_factory",
        lambda: SessionContext(session),
    )

    await publisher.publish_event(event)

    publish.assert_awaited_once()
    assert event.status is OutboxStatus.PUBLISHED
    assert event.published_at is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_event_retries_and_marks_failed_after_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = build_event(attempts=2)
    session = SimpleNamespace(
        get=AsyncMock(return_value=event),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        publisher.broker,
        "publish",
        AsyncMock(side_effect=RuntimeError("broker unavailable")),
    )
    monkeypatch.setattr(
        publisher,
        "async_session_factory",
        lambda: SessionContext(session),
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await publisher.publish_event(event)

    assert event.attempts == 3
    assert event.status is OutboxStatus.FAILED
    assert event.last_error == "broker unavailable"
    assert event.next_attempt_at > datetime.now(UTC) - timedelta(seconds=1)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_event_does_not_fail_if_event_was_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = build_event()
    session = SimpleNamespace(
        get=AsyncMock(return_value=None),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(publisher.broker, "publish", AsyncMock())
    monkeypatch.setattr(
        publisher,
        "async_session_factory",
        lambda: SessionContext(session),
    )

    await publisher.publish_event(event)

    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_publisher_closes_broker_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect = AsyncMock()
    stop = AsyncMock()
    monkeypatch.setattr(publisher.broker, "connect", connect)
    monkeypatch.setattr(publisher.broker, "stop", stop)
    monkeypatch.setattr(
        publisher,
        "get_pending_events",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        publisher.asyncio,
        "sleep",
        AsyncMock(side_effect=RuntimeError("stop test loop")),
    )

    with pytest.raises(RuntimeError, match="stop test loop"):
        await publisher.run_publisher()

    connect.assert_awaited_once()
    stop.assert_awaited_once()
