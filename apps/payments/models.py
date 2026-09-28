from django.db import models
from django.db.models import Q

from apps.common.models import BaseModel


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SimulatedOutcome(models.TextChoices):
    """What the simulated gateway should do. PENDING leaves the result to the webhook."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"


class Payment(BaseModel):
    """One payment attempt for a booking.

    PENDING → SUCCESS | FAILED; both outcomes are terminal. The partial unique indexes make
    "paid twice" and "two attempts in flight" impossible even if application code has a bug.
    """

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    provider = models.CharField(max_length=32)
    provider_reference = models.CharField(max_length=64, null=True, blank=True)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    request_hash = models.CharField(max_length=64)
    failure_reason = models.CharField(max_length=255, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payments_amount_positive"),
            models.CheckConstraint(
                condition=Q(status__in=PaymentStatus.values), name="payments_status_valid"
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=PaymentStatus.PENDING, completed_at__isnull=True)
                    | (~Q(status=PaymentStatus.PENDING) & Q(completed_at__isnull=False))
                ),
                name="payments_completed_at_matches_status",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_reference"],
                name="payments_provider_reference_unique",
            ),
            models.UniqueConstraint(
                fields=["booking"],
                condition=Q(status=PaymentStatus.SUCCESS),
                name="payments_one_success_per_booking",
            ),
            models.UniqueConstraint(
                fields=["booking"],
                condition=Q(status=PaymentStatus.PENDING),
                name="payments_one_pending_per_booking",
            ),
            # NULL keys never collide in PostgreSQL, so key-less requests are unaffected.
            models.UniqueConstraint(
                fields=["booking", "idempotency_key"],
                name="payments_booking_idempotency_key_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"Payment {self.id} ({self.status})"
