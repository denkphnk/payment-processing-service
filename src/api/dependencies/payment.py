from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_session
from src.domain.services.payment_service import PaymentService


async def get_payment_service(
    session: AsyncSession = Depends(get_session),
) -> PaymentService:
    return PaymentService(session)
