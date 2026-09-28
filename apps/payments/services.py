"""Payment processing.

Two entry points change payment state, and both end in `apply_payment_result()`:
  * `create_payment()`   the synchronous result from the (simulated) gateway
  * the webhook          asynchronous notifications from the provider (apps.payments.webhooks)

`apply_payment_result()` is idempotent: re-applying an outcome is a no-op, and a conflicting
outcome for an already-settled payment is refused. Lock order is always booking, then payment.
"""

import hashlib
import json
import logging
import uuid
from enum import StrEnum

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings import services as booking_services
from apps.bookings.exceptions import BookingNotPayable, PaymentInProgress
from apps.bookings.models import Booking, BookingStatus
from apps.common.db import violated_constraint
from apps.payments.exceptions import (
    IdempotencyKeyReused,
    PaymentGatewayUnavailable,
    PaymentNotFound,
)
from apps.payments.gateway import GatewayError, GatewayResult, get_gateway
from apps.payments.models import Payment, PaymentStatus

logger = logging.getLogger(__name__)


class ApplyResult(StrEnum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    CONFLICT = "conflict"


_BOOKING_TARGET = {
    PaymentStatus.SUCCESS: BookingStatus.CONFIRMED,
    PaymentStatus.FAILED: BookingStatus.FAILED,
}


# --- Queries ----------------------------------------------------------------------------------


def visible_payments(user: User) -> QuerySet[Payment]:
    queryset = Payment.objects.select_related("booking")
    return queryset if user.is_staff else queryset.filter(booking__user=user)


def get_visible_payment(*, user: User, payment_id: uuid.UUID) -> Payment:
    try:
        return visible_payments(user).get(pk=payment_id)
    except Payment.DoesNotExist as exc:
        raise PaymentNotFound() from exc


def lock_booking_and_payment(payment_id: uuid.UUID) -> tuple[Booking, Payment]:
    """Row-lock a payment and its booking (booking first). Call inside transaction.atomic()."""
    try:
        booking_id = Payment.objects.values_list("booking_id", flat=True).get(pk=payment_id)
    except Payment.DoesNotExist as exc:
        raise PaymentNotFound() from exc
    booking = Booking.objects.select_for_update().get(pk=booking_id)
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    return booking, payment


# --- Commands ---------------------------------------------------------------------------------


def request_fingerprint(*, booking_id: uuid.UUID, simulate_outcome: str) -> str:
    """Stable hash of the request body, to detect an Idempotency-Key reused for another request."""
    canonical = json.dumps(
        {"booking_id": str(booking_id), "simulate_outcome": simulate_outcome}, sort_keys=True
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_payment(
    *,
    user: User,
    booking_id: uuid.UUID,
    simulate_outcome: str,
    idempotency_key: str | None = None,
) -> tuple[Payment, bool]:
    """Charge a booking through the gateway. Returns (payment, created).

    Tx1 records a PENDING attempt under the booking lock, the gateway is called with no
    transaction open (a real provider call must never hold row locks), and Tx2 applies the
    result. If the process dies between the steps, the PENDING payment is an accurate record
    that a charge was attempted; the webhook settles it later.
    """
    gateway = get_gateway()
    fingerprint = request_fingerprint(booking_id=booking_id, simulate_outcome=simulate_outcome)

    with transaction.atomic():
        booking = booking_services.lock_own_booking(user=user, booking_id=booking_id)
        if idempotency_key:
            existing = Payment.objects.filter(
                booking=booking, idempotency_key=idempotency_key
            ).first()
            if existing is not None:
                if existing.request_hash != fingerprint:
                    raise IdempotencyKeyReused()
                logger.info("payment.idempotent_replay", extra={"payment_id": str(existing.id)})
                return existing, False
        booking_services.assert_payable(booking)
        if booking.payments.filter(status=PaymentStatus.PENDING).exists():
            raise PaymentInProgress()
        payment = _insert_pending_payment(booking, gateway.name, idempotency_key, fingerprint)

    logger.info(
        "payment.created",
        extra={"payment_id": str(payment.id), "booking_id": str(booking.id)},
    )

    try:
        result = gateway.charge(payment, simulate_outcome=simulate_outcome)
    except GatewayError as exc:
        logger.warning("payment.gateway_error", extra={"payment_id": str(payment.id)})
        raise PaymentGatewayUnavailable() from exc

    return record_gateway_result(payment.id, result), True


def _insert_pending_payment(
    booking: Booking, provider: str, idempotency_key: str | None, fingerprint: str
) -> Payment:
    try:
        with transaction.atomic():
            return Payment.objects.create(
                booking=booking,
                amount=booking.amount,  # copied from the booking, never from the client
                currency=booking.currency,
                provider=provider,
                idempotency_key=idempotency_key,
                request_hash=fingerprint,
            )
    except IntegrityError as exc:
        # Backstops for the checks above; reachable only if those checks are ever bypassed.
        constraint = violated_constraint(exc)
        if constraint == "payments_one_pending_per_booking":
            raise PaymentInProgress() from exc
        if constraint == "payments_one_success_per_booking":
            raise BookingNotPayable("This booking has already been paid.") from exc
        raise


def record_gateway_result(payment_id: uuid.UUID, result: GatewayResult) -> Payment:
    with transaction.atomic():
        booking, payment = lock_booking_and_payment(payment_id)
        payment.provider_reference = result.reference
        payment.save(update_fields=["provider_reference", "updated_at"])
        if result.status != PaymentStatus.PENDING:
            apply_payment_result(
                booking=booking,
                payment=payment,
                status=result.status,
                failure_reason=result.failure_reason,
                source="gateway",
            )
    return payment


def apply_payment_result(
    *,
    booking: Booking,
    payment: Payment,
    status: str,
    failure_reason: str = "",
    source: str,
) -> ApplyResult:
    """Settle a payment and move its booking. Caller holds locks on booking, then payment."""
    if status not in _BOOKING_TARGET:
        raise ValueError(f"Not a final payment status: {status!r}")
    log_extra = {
        "payment_id": str(payment.id),
        "booking_id": str(booking.id),
        "source": source,
    }

    if payment.status == status:
        logger.info("payment.result_already_applied", extra={**log_extra, "status": status})
        return ApplyResult.ALREADY_APPLIED

    if payment.status != PaymentStatus.PENDING:
        # Terminal states are final. FAILED then SUCCESS may mean money was captured
        # without a confirmed booking, so it's logged at ERROR for reconciliation.
        level = logging.ERROR if status == PaymentStatus.SUCCESS else logging.WARNING
        logger.log(
            level,
            "payment.conflicting_result",
            extra={**log_extra, "current_status": payment.status, "incoming_status": status},
        )
        return ApplyResult.CONFLICT

    payment.status = status
    payment.failure_reason = failure_reason if status == PaymentStatus.FAILED else ""
    payment.completed_at = timezone.now()
    payment.save(update_fields=["status", "failure_reason", "completed_at", "updated_at"])
    logger.info(f"payment.{status.lower()}", extra=log_extra)

    if booking.status == BookingStatus.PENDING:
        booking_services.transition(
            booking, _BOOKING_TARGET[status], reason=f"payment_{status.lower()}"
        )
    else:
        # Cancelling is blocked while a payment is pending, so this indicates a bug or a
        # manual change; a successful charge here would need a refund.
        logger.error(
            "payment.result_for_settled_booking",
            extra={**log_extra, "booking_status": booking.status, "payment_status": status},
        )
    return ApplyResult.APPLIED
