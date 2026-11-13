from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


Currency = Literal["RUB", "USD", "EUR"]


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: Currency
    description: str | None = Field(default=None, max_length=1000)
    metadata: dict = Field(default_factory=dict)
    webhook_url: HttpUrl


class PaymentResponse(BaseModel):
    payment_id: UUID
    status: Literal["pending", "succeeded", "failed"]
    created_at: datetime


class PaymentDetails(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: Decimal
    currency: Currency
    description: str | None
    metadata: dict = Field(validation_alias="metadata_json")
    status: Literal["pending", "succeeded", "failed"]
    created_at: datetime
    processed_at: datetime | None
