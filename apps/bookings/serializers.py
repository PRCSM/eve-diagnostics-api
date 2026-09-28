from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from apps.bookings.models import Booking, BookingStatus
from apps.catalog.models import DiagnosticCentre
from apps.catalog.serializers import DiagnosticTestSummarySerializer


class AwareDateTimeField(serializers.DateTimeField):
    """ISO 8601 datetime that must carry a timezone offset.

    Appointment times without an offset are ambiguous, so they're rejected rather than
    silently interpreted in the server's timezone.
    """

    default_error_messages = {
        "naive": "Include a timezone offset, e.g. 2026-10-05T09:30:00+05:30.",
    }

    def to_internal_value(self, value):
        if isinstance(value, str):
            try:
                parsed = parse_datetime(value.strip())
            except ValueError:
                parsed = None  # let the parent field report the format error
            if parsed is not None and timezone.is_naive(parsed):
                self.fail("naive")
        return super().to_internal_value(value)


class BookingCentreSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticCentre
        fields = ["id", "name", "city"]
        read_only_fields = fields


class BookingSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(read_only=True)
    centre = BookingCentreSerializer(source="offering.centre", read_only=True)
    test = DiagnosticTestSummarySerializer(source="offering.test", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "user_id",
            "status",
            "appointment_at",
            "amount",
            "currency",
            "centre",
            "test",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class BookingCreateSerializer(serializers.Serializer):
    """Only these fields are accepted; amount and status are always set by the server."""

    centre_id = serializers.UUIDField()
    test_id = serializers.UUIDField()
    appointment_at = AwareDateTimeField()

    def validate_appointment_at(self, value: datetime) -> datetime:
        now = timezone.now()
        if value <= now:
            raise serializers.ValidationError("Must be in the future.")
        max_days = settings.BOOKING_MAX_ADVANCE_DAYS
        if value > now + timedelta(days=max_days):
            raise serializers.ValidationError(f"Must be within {max_days} days from now.")
        return value


class BookingListQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=BookingStatus.choices, required=False)
