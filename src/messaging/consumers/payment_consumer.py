import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone

from faststream import FastStream
from sqlalchemy import update

from src.core.database import async_session_factory
from src.data.models.payment import Payment
from src.messaging.broker import broker, payments_queue

logger = logging.getLogger(__name__)

app = FastStream(broker)


@broker.subscriber(payments_queue)
async def process_payment(message: dict) -> None:
    payment_id = uuid.UUID(message["payment_id"])

    processing_time = random.uniform(2, 5)
    await asyncio.sleep(processing_time)

    payment_status = (
        "succeeded" if random.random() < 0.9 else "failed"
    )

    async with async_session_factory() as session:
        result = await session.execute(
            update(Payment)
            .where(
                Payment.id == payment_id,
                Payment.status == "pending",
            )
            .values(
                status=payment_status,
                processed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

        if result.rowcount == 0:
            logger.warning(
                "Payment %s not found or already processed",
                payment_id,
            )
            return

    logger.info(
        "Payment %s processed: %s",
        payment_id,
        payment_status,
    )
