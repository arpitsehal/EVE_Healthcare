from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Booking, BookingStatus, DiagnosticCentre, DiagnosticTest, User
from app.schemas import BookingCreate, BookingRead


router = APIRouter(prefix="/bookings", tags=["Bookings"])


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Booking:
    centre = db.get(DiagnosticCentre, payload.centre_id)
    diagnostic_test = db.get(DiagnosticTest, payload.test_id)
    if centre is None or not centre.is_active:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    if diagnostic_test is None or not diagnostic_test.is_active:
        raise HTTPException(status_code=404, detail="Diagnostic test not found")
    if diagnostic_test.centre_id != centre.id:
        raise HTTPException(status_code=422, detail="The test is not offered by this centre")
    booking = Booking(
        user_id=user.id,
        test_id=diagnostic_test.id,
        centre_id=centre.id,
        appointment_at=payload.appointment_at,
        amount=diagnostic_test.price,
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@router.get("", response_model=list[BookingRead])
def list_bookings(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Booking]:
    statement = (
        select(Booking)
        .where(Booking.user_id == user.id)
        .order_by(Booking.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(statement).all())


@router.get("/{booking_id}", response_model=BookingRead)
def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Booking:
    booking = db.scalar(select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id))
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.post("/{booking_id}/cancel", response_model=BookingRead)
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Booking:
    booking = db.scalar(select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id))
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != BookingStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending bookings can be cancelled")
    if booking.appointment_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="A past appointment cannot be cancelled")
    booking.status = BookingStatus.CANCELLED
    db.commit()
    db.refresh(booking)
    return booking