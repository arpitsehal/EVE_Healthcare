from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CentreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    location: str = Field(min_length=1, max_length=255)


class CentreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    location: str | None = Field(default=None, min_length=1, max_length=255)


class TestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class TestUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)


class TestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    centre_id: int
    name: str
    description: str | None
    price: Decimal


class CentreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str
    tests: list[TestRead]


class BookingCreate(BaseModel):
    test_id: int = Field(gt=0)
    centre_id: int = Field(gt=0)
    appointment_at: datetime

    @field_validator("appointment_at")
    @classmethod
    def require_future_timezone_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("appointment_at must include a timezone")
        if value <= datetime.now(timezone.utc):
            raise ValueError("appointment_at must be in the future")
        return value


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    test_id: int
    centre_id: int
    appointment_at: datetime
    amount: Decimal
    status: str


class PaymentStatusValue(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PaymentCreate(BaseModel):
    booking_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=128)
    simulate_status: PaymentStatusValue = PaymentStatusValue.SUCCESS


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    status: str
    amount: Decimal


class WebhookRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    payment_id: int = Field(gt=0)
    status: PaymentStatusValue


class WebhookRead(BaseModel):
    event_id: str
    payment_id: int
    status: str
    duplicate: bool