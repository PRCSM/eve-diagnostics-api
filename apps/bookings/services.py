"""Booking lifecycle. Every status change goes through `transition()` under a row lock."""

import logging
import uuid
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings import state
from apps.bookings.exceptions import (
    BookingNotCancellable,
    BookingNotFound,
    BookingNotPayable,
    DuplicateBooking,
)
from apps.bookings.models import Booking, BookingStatus
from apps.catalog import services as catalog_services
from apps.catalog.models import CURRENCY
from apps.common.db import violated_constraint

logger = logging.getLogger(__name__)


# --- Queries ----------------------------------------------------------------------------------


def visible_bookings(user: User) -> QuerySet[Booking]:
    """Patients see their own bookings; staff see everyone's (read-only)."""
    queryset = Booking.objects.select_related("offering__centre", "offering__test")
    return queryset if user.is_staff else queryset.filter(user=user)


def get_visible_booking(*, user: User, booking_id: uuid.UUID) -> Booking:
    try:
        return visible_bookings(user).get(pk=booking_id)
    except Booking.DoesNotExist as exc:
        # Same response whether it doesn't exist or belongs to someone else.
        raise BookingNotFound() from exc


def lock_own_booking(*, user: User, booking_id: uuid.UUID) -> Booking:
    """Row-lock one of the caller's bookings. Must run inside transaction.atomic()."""
    try:
        return Booking.objects.select_for_update().get(pk=booking_id, user=user)
    except Booking.DoesNotExist as exc:
        raise BookingNotFound() from exc


# --- Commands ---------------------------------------------------------------------------------


def create_booking(
    *, user: User, centre_id: uuid.UUID, test_id: uuid.UUID, appointment_at: datetime
) -> Booking:
    offering = catalog_services.get_bookable_offering(centre_id=centre_id, test_id=test_id)
    try:
        with transaction.atomic():
            booking = Booking.objects.create(
                user=user,
                offering=offering,
                appointment_at=appointment_at,
                amount=offering.price,  # server-side price, never the client's
                currency=CURRENCY,
            )
    except IntegrityError as exc:
        if violated_constraint(exc) == "bookings_active_unique":
            raise DuplicateBooking() from exc
        raise
    logger.info(
        "booking.created",
        extra={"booking_id": str(booking.id), "user_id": str(user.id)},
    )
    return booking


def cancel_booking(*, user: User, booking_id: uuid.UUID) -> Booking:
    """Cancel a pending booking. Cancelling an already-cancelled booking is a no-op."""
    with transaction.atomic():
        booking = lock_own_booking(user=user, booking_id=booking_id)
        if booking.status == BookingStatus.CANCELLED:
            return booking
        if booking.status != BookingStatus.PENDING:
            raise BookingNotCancellable(
                f"A {booking.status} booking cannot be cancelled.",
                details={"status": booking.status},
            )
        transition(booking, BookingStatus.CANCELLED, reason="cancelled_by_patient")
    return booking


def transition(booking: Booking, target: str, *, reason: str) -> None:
    """Move a booking to `target`. The caller must hold the booking's row lock."""
    state.assert_transition(booking.status, target)
    previous = booking.status
    booking.status = target
    booking.save(update_fields=["status", "updated_at"])
    logger.info(
        "booking.status_changed",
        extra={
            "booking_id": str(booking.id),
            "from_status": previous,
            "to_status": target,
            "reason": reason,
        },
    )


def assert_payable(booking: Booking) -> None:
    if booking.status != BookingStatus.PENDING:
        raise BookingNotPayable(
            f"Booking is {booking.status} and cannot accept a payment.",
            details={"status": booking.status},
        )
    if booking.appointment_at <= timezone.now():
        raise BookingNotPayable(
            "The appointment time has passed.", details={"status": booking.status}
        )
