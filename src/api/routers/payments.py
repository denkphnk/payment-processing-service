from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from src.api.dependencies.auth import verify_api_key
from src.api.dependencies.payment import get_payment_service
from src.domain.schemas.payment import (
    PaymentCreate,
    PaymentDetails,
    PaymentResponse,
)
from src.domain.services.payment_service import PaymentService


router = APIRouter(
    prefix="/api/v1/payments",
    tags=["Payments"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_payment(
    data: PaymentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentResponse:
    payment = await service.create_payment(data, idempotency_key)

    return PaymentResponse(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentDetails,
)
async def get_payment(
    payment_id: UUID,
    service: PaymentService = Depends(get_payment_service),
) -> PaymentDetails:
    payment = await service.get_payment(payment_id)

    return PaymentDetails.model_validate(payment)
