import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import WEBHOOK_SECRET
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Booking, BookingStatus, Payment, PaymentStatus, User, WebhookEvent
from app.schemas import PaymentCreate, PaymentRead, WebhookRead, WebhookRequest


router = APIRouter(tags=["Payments"])


def apply_payment_status(booking: Booking, payment: Payment, payment_status: PaymentStatus) -> None:
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="A cancelled booking cannot be paid")
    payment.status = payment_status
    booking.status = (
        BookingStatus.CONFIRMED if payment_status == PaymentStatus.SUCCESS else BookingStatus.FAILED
    )


@router.post("/payments/", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Payment:
    existing = db.scalar(
        select(Payment).where(
            Payment.user_id == user.id, Payment.idempotency_key == payload.idempotency_key
        )
    )
    if existing is not None:
        if existing.booking_id != payload.booking_id:
            raise HTTPException(status_code=409, detail="Idempotency key was used for another booking")
        return existing

    booking = db.scalar(select(Booking).where(Booking.id == payload.booking_id, Booking.user_id == user.id))
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status not in (BookingStatus.PENDING, BookingStatus.FAILED):
        raise HTTPException(status_code=409, detail="This booking cannot accept another payment")

    payment = Payment(
        booking_id=booking.id,
        user_id=user.id,
        idempotency_key=payload.idempotency_key,
        amount=booking.amount,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    try:
        db.flush()
        apply_payment_status(booking, payment, PaymentStatus(payload.simulate_status.value))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Payment).where(
                Payment.user_id == user.id, Payment.idempotency_key == payload.idempotency_key
            )
        )
        if existing is None or existing.booking_id != payload.booking_id:
            raise HTTPException(status_code=409, detail="Payment idempotency conflict") from None
        return existing
    db.refresh(payment)
    return payment


@router.post("/payments/webhook/", response_model=WebhookRead)
def payment_webhook(
    payload: WebhookRequest,
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> WebhookRead:
    if x_webhook_secret is None or not hmac.compare_digest(x_webhook_secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook credentials")

    prior_event = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == payload.event_id))
    if prior_event is not None:
        if prior_event.payment_id != payload.payment_id or prior_event.status.value != payload.status.value:
            raise HTTPException(status_code=409, detail="Event ID was already used with a different payload")
        return WebhookRead(
            event_id=prior_event.event_id,
            payment_id=prior_event.payment_id,
            status=prior_event.status.value,
            duplicate=True,
        )

    payment = db.get(Payment, payload.payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    booking = db.get(Booking, payment.booking_id)
    requested_status = PaymentStatus(payload.status.value)
    if payment.status == PaymentStatus.SUCCESS and requested_status == PaymentStatus.FAILED:
        raise HTTPException(status_code=409, detail="A successful payment cannot be downgraded")

    event = WebhookEvent(event_id=payload.event_id, payment_id=payment.id, status=requested_status)
    db.add(event)
    apply_payment_status(booking, payment, requested_status)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior_event = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == payload.event_id))
        if prior_event is None:
            raise HTTPException(status_code=409, detail="Webhook event conflict") from None
        if prior_event.payment_id != payload.payment_id or prior_event.status.value != payload.status.value:
            raise HTTPException(status_code=409, detail="Event ID was already used with a different payload") from None
        return WebhookRead(
            event_id=prior_event.event_id,
            payment_id=prior_event.payment_id,
            status=prior_event.status.value,
            duplicate=True,
        )
    return WebhookRead(
        event_id=event.event_id,
        payment_id=payment.id,
        status=payment.status.value,
        duplicate=False,
    )