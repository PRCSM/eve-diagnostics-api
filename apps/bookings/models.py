from django.conf import settings
from django.db import models

from apps.catalog.models import CURRENCY
from apps.common.models import BaseModel


class BookingStatus(models.TextChoices):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ACTIVE_BOOKING_STATUSES = [BookingStatus.PENDING, BookingStatus.CONFIRMED]


class Booking(BaseModel):
    """A patient's appointment for one test at one centre.

    `offering` (centre + test) makes "a test the centre doesn't offer" unrepresentable.
    `amount` is a snapshot of the price at booking time, so later price changes don't
    rewrite history.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings"
    )
    offering = models.ForeignKey(
        "catalog.CentreTest", on_delete=models.PROTECT, related_name="bookings"
    )
    appointment_at = models.DateTimeField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default=CURRENCY)
    status = models.CharField(
        max_length=16, choices=BookingStatus.choices, default=BookingStatus.PENDING
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"], name="bookings_user_created_idx")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="bookings_amount_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=BookingStatus.values), name="bookings_status_valid"
            ),
            # Blocks double-submitted bookings; cancelled/failed ones don't block rebooking.
            models.UniqueConstraint(
                fields=["user", "offering", "appointment_at"],
                condition=models.Q(status__in=ACTIVE_BOOKING_STATUSES),
                name="bookings_active_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"Booking {self.id} ({self.status})"
