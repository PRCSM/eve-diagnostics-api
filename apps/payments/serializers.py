from django.conf import settings
from rest_framework import serializers

from apps.payments.models import Payment, SimulatedOutcome


class PaymentCreateSerializer(serializers.Serializer):
    """Only the booking is taken from the client; the amount always comes from the booking."""

    booking_id = serializers.UUIDField()
    simulate_outcome = serializers.ChoiceField(
        choices=SimulatedOutcome.choices,
        required=False,
        help_text=(
            "Simulation control. SUCCESS or FAILED settle immediately; PENDING leaves the "
            "result to the payment webhook. Defaults to PAYMENT_SIMULATION_DEFAULT_OUTCOME."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        # Read at request time (not import time) so the setting can change per environment.
        attrs.setdefault("simulate_outcome", settings.PAYMENT_SIMULATION_DEFAULT_OUTCOME)
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    booking_id = serializers.UUIDField(read_only=True)
    booking_status = serializers.CharField(source="booking.status", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "booking_id",
            "status",
            "amount",
            "currency",
            "provider",
            "provider_reference",
            "failure_reason",
            "booking_status",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields
