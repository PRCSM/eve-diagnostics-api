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
    # NULL (not "") when absent: NULLs never collide in the unique constraints below.
    provider_reference = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
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


class WebhookEventStatus(models.TextChoices):
    RECEIVED = "RECEIVED"  # stored, not yet processed
    PROCESSED = "PROCESSED"  # applied (or already applied) to the payment
    IGNORED = "IGNORED"  # acknowledged but not applied: unknown type or conflicting result
    FAILED = "FAILED"  # processing failed; eligible for retry


class WebhookEvent(BaseModel):
    """Inbox of provider notifications. One row per (provider, event_id), however many
    times the provider delivers it. `created_at` is when it was first received."""

    provider = models.CharField(max_length=32)
    event_id = models.CharField(max_length=128)
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=WebhookEventStatus.choices, default=WebhookEventStatus.RECEIVED
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="webhook_events",
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"], name="webhook_events_provider_event_unique"
            ),
            models.CheckConstraint(
                condition=Q(status__in=WebhookEventStatus.values),
                name="webhook_events_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="webhook_events_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_id} ({self.status})"
