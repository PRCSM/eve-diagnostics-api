"""Table-driven tests for the single function that settles payments."""

import pytest
from django.db import transaction

from apps.bookings.models import BookingStatus
from apps.payments.models import PaymentStatus
from apps.payments.services import ApplyResult, apply_payment_result, lock_booking_and_payment

pytestmark = pytest.mark.django_db


def apply(payment, status):
    with transaction.atomic():
        booking, locked = lock_booking_and_payment(payment.id)
        result = apply_payment_result(booking=booking, payment=locked, status=status, source="test")
    payment.refresh_from_db()
    booking.refresh_from_db()
    return result, payment, booking


@pytest.mark.parametrize(
    "incoming, expected_payment, expected_booking",
    [
        (PaymentStatus.SUCCESS, PaymentStatus.SUCCESS, BookingStatus.CONFIRMED),
        (PaymentStatus.FAILED, PaymentStatus.FAILED, BookingStatus.FAILED),
    ],
)
def test_pending_payment_is_settled(
    booking, make_payment, incoming, expected_payment, expected_booking
):
    result, payment, booking = apply(make_payment(booking), incoming)

    assert result == ApplyResult.APPLIED
    assert payment.status == expected_payment
    assert payment.completed_at is not None
    assert booking.status == expected_booking


@pytest.mark.parametrize(
    "current, booking_status",
    [
        (PaymentStatus.SUCCESS, BookingStatus.CONFIRMED),
        (PaymentStatus.FAILED, BookingStatus.FAILED),
    ],
)
def test_reapplying_the_same_result_is_a_no_op(
    user, make_booking, make_payment, current, booking_status
):
    booking = make_booking(user, status=booking_status)
    payment = make_payment(booking, status=current)
    completed_at = payment.completed_at

    result, payment, booking = apply(payment, current)

    assert result == ApplyResult.ALREADY_APPLIED
    assert payment.completed_at == completed_at
    assert booking.status == booking_status


@pytest.mark.parametrize(
    "current, booking_status, incoming",
    [
        (PaymentStatus.SUCCESS, BookingStatus.CONFIRMED, PaymentStatus.FAILED),
        (PaymentStatus.FAILED, BookingStatus.FAILED, PaymentStatus.SUCCESS),
    ],
)
def test_conflicting_result_never_overwrites_a_final_state(
    user, make_booking, make_payment, current, booking_status, incoming, caplog
):
    booking = make_booking(user, status=booking_status)

    result, payment, booking = apply(make_payment(booking, status=current), incoming)

    assert result == ApplyResult.CONFLICT
    assert payment.status == current
    assert booking.status == booking_status
    assert "payment.conflicting_result" in caplog.text


def test_success_for_a_cancelled_booking_is_recorded_but_booking_stays_cancelled(
    user, make_booking, make_payment, caplog
):
    booking = make_booking(user, status=BookingStatus.CANCELLED)

    result, payment, booking = apply(make_payment(booking), PaymentStatus.SUCCESS)

    assert result == ApplyResult.APPLIED
    assert payment.status == PaymentStatus.SUCCESS
    assert booking.status == BookingStatus.CANCELLED
    assert "payment.result_for_settled_booking" in caplog.text


def test_pending_is_not_a_final_status(booking, make_payment):
    with pytest.raises(ValueError):
        apply(make_payment(booking), PaymentStatus.PENDING)
