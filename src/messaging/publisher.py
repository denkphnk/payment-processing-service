
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from src.core.database import async_session_factory
from src.data.models.outbox import Outbox
from src.data.models.payment import Payment
from src.messaging.broker import broker, payments_queue

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2
BATCH_SIZE = 100
MAX_ATTEMPTS = 3


async def get_pending_events() -> list[Outbox]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(Outbox)
            .where(
                Outbox.published_at.is_(None),
                Outbox.next_attempt_at <= datetime.now(timezone.utc),
                Outbox.attempts < MAX_ATTEMPTS,
            )
            .order_by(Outbox.created_at)
            .limit(BATCH_SIZE)
        )
        return list(result.scalars().all())


async def publish_event(event: Outbox) -> None:
    try:
        await broker.publish(
            message=event.payload,
            queue=payments_queue,
            routing_key="payments.new",
        )

    except Exception as exc:
        async with async_session_factory() as session:
            db_event = await session.get(Outbox, event.id)

            if db_event is not None:
                db_event.attempts += 1
                db_event.last_error = str(exc)
                db_event.next_attempt_at = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=2 ** db_event.attempts)
                )
                await session.commit()

        raise

    async with async_session_factory() as session:
        db_event = await session.get(Outbox, event.id)

        if db_event is not None:
            db_event.published_at = datetime.now(timezone.utc)
            await session.commit()


async def run_publisher() -> None:
    await broker.connect()

    logger.info("Outbox publisher started")

    try:
        while True:
            events = await get_pending_events()

            for event in events:
                try:
                    await publish_event(event)
                    logger.info("Published event %s", event.id)

                except Exception:
                    logger.exception(
                        "Failed to publish event %s",
                        event.id,
                    )

            await asyncio.sleep(POLL_INTERVAL)

    finally:
        await broker.close()
        logger.info("Outbox publisher stopped")


if __name__ == "__main__":
    asyncio.run(run_publisher())
