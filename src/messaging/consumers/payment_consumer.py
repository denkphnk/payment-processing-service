import asyncio
import logging
import random
import uuid
from datetime import UTC, datetime

import httpx
from faststream import FastStream
from faststream.middlewares import AckPolicy
from sqlalchemy import select, update

from src.core.database import async_session_factory
from src.data.models.payment import Payment
from src.messaging.broker import broker, payments_dlq, payments_queue

logger = logging.getLogger(__name__)

app = FastStream(broker)

WEBHOOK_MAX_ATTEMPTS = 3
WEBHOOK_RETRY_DELAY = 1
WEBHOOK_TIMEOUT = 10


@app.after_startup
async def declare_dead_letter_queue() -> None:
    await broker.declare_queue(payments_dlq)


async def send_webhook(payment: Payment) -> None:
    payload = {
        "payment_id": str(payment.id),
        "status": payment.status,
    }

    async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
        for attempt in range(1, WEBHOOK_MAX_ATTEMPTS + 1):
            try:
                response = await client.post(
                    payment.webhook_url,
                    json=payload,
                )
                response.raise_for_status()
                return
            except httpx.HTTPError:
                if attempt == WEBHOOK_MAX_ATTEMPTS:
                    logger.exception(
                        "Webhook delivery failed after %s attempts for payment %s",
                        WEBHOOK_MAX_ATTEMPTS,
                        payment.id,
                    )
                    raise

                delay = WEBHOOK_RETRY_DELAY * 2 ** (attempt - 1)
                logger.warning(
                    "Webhook delivery failed for payment %s, retrying in %s seconds",
                    payment.id,
                    delay,
                )
                await asyncio.sleep(delay)


@broker.subscriber(payments_queue, ack_policy=AckPolicy.NACK_ON_ERROR)
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
                processed_at=datetime.now(UTC),
            )
        )
        await session.commit()

        if result.rowcount == 0:
            logger.warning(
                "Payment %s not found or already processed",
                payment_id,
            )
            return

        payment = await session.scalar(
            select(Payment).where(Payment.id == payment_id)
        )

    if payment is None:
        logger.error(
            "Payment %s was updated but could not be loaded for webhook",
            payment_id,
        )
        raise RuntimeError(
            f"Payment {payment_id} was updated but could not be loaded"
        )

    await send_webhook(payment)

    logger.info(
        "Payment %s processed: %s",
        payment_id,
        payment_status,
    )
