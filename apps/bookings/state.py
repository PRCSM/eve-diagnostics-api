"""Booking state machine. Pure functions, no database access.

    PENDING ──payment SUCCESS──▶ CONFIRMED
       │  ──payment FAILED───▶ FAILED
       └──patient cancels───▶ CANCELLED

CONFIRMED, FAILED and CANCELLED are terminal.
"""

from apps.bookings.exceptions import InvalidBookingTransition
from apps.bookings.models import BookingStatus

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    BookingStatus.PENDING: frozenset(
        {BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED}
    ),
    BookingStatus.CONFIRMED: frozenset(),
    BookingStatus.FAILED: frozenset(),
    BookingStatus.CANCELLED: frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidBookingTransition(
            f"A {current} booking cannot become {target}.",
            details={"current_status": current, "requested_status": target},
        )
