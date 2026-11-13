import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.outbox import Outbox
from src.data.models.payment import Payment
from src.data.repositories.outbox_repository import OutboxRepository
from src.data.repositories.payment_repository import PaymentRepository
from src.domain.schemas.payment import PaymentCreate


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.payment_repository = PaymentRepository(session)
        self.outbox_repository = OutboxRepository(session)

    async def create_payment(
        self,
        data: PaymentCreate,
        idempotency_key: str,
    ) -> Payment:
        try:
            async with self.session.begin():
                existing = await self.payment_repository.get_by_idempotency_key(
                    idempotency_key
                )

                if existing:
                    self._check_idempotency(existing, data)
                    return existing

                payment = Payment(
                    amount=data.amount,
                    currency=data.currency,
                    description=data.description,
                    metadata_json=data.metadata,
                    webhook_url=str(data.webhook_url),
                    idempotency_key=idempotency_key,
                    status="pending",
                )

                await self.payment_repository.create(payment)

                event = Outbox(
                    aggregate_id=payment.id,
                    event_type="payment.created",
                    payload={
                        "payment_id": str(payment.id),
                    },
                )

                await self.outbox_repository.create(event)

            return payment

        except IntegrityError:
            existing = await self.payment_repository.get_by_idempotency_key(
                idempotency_key
            )

            if existing:
                self._check_idempotency(existing, data)
                return existing

            raise

    @staticmethod
    def _check_idempotency(
        existing: Payment,
        data: PaymentCreate,
    ) -> None:
        if (
            existing.amount != data.amount
            or existing.currency != data.currency
            or existing.description != data.description
            or existing.metadata_json != data.metadata
            or existing.webhook_url != str(data.webhook_url)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key already used with different data",
            )

    async def get_payment(self, payment_id: uuid.UUID) -> Payment:
        payment = await self.payment_repository.get_by_id(payment_id)

        if payment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found",
            )

        return payment
