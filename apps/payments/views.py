import re

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.payments import services, webhooks
from apps.payments.serializers import PaymentCreateSerializer, PaymentSerializer

IDEMPOTENCY_HEADER = "Idempotency-Key"
_VALID_IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]{1,255}$")  # visible ASCII, no spaces


def _idempotency_key(request) -> str | None:
    key = request.headers.get(IDEMPOTENCY_HEADER)
    if key is None:
        return None
    if not _VALID_IDEMPOTENCY_KEY.match(key):
        raise serializers.ValidationError(
            {IDEMPOTENCY_HEADER: ["Must be 1-255 visible ASCII characters."]}
        )
    return key


class PaymentCreateView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "payments"

    @extend_schema(
        tags=["payments"],
        request=PaymentCreateSerializer,
        parameters=[
            OpenApiParameter(
                IDEMPOTENCY_HEADER,
                str,
                OpenApiParameter.HEADER,
                required=False,
                description=(
                    "Client-generated key. Retrying with the same key returns the original "
                    "payment (200) instead of creating a new one."
                ),
            )
        ],
        responses={201: PaymentSerializer, 200: PaymentSerializer},
    )
    def post(self, request):
        """Pay for one of your bookings through the simulated gateway."""
        idempotency_key = _idempotency_key(request)
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment, created = services.create_payment(
            user=request.user, idempotency_key=idempotency_key, **serializer.validated_data
        )
        return Response(
            PaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PaymentDetailView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["payments"], responses={200: PaymentSerializer})
    def get(self, request, payment_id):
        payment = services.get_visible_payment(user=request.user, payment_id=payment_id)
        return Response(PaymentSerializer(payment).data)


_WebhookResponse = inline_serializer(
    name="WebhookResponse",
    fields={
        "event_id": serializers.CharField(),
        "result": serializers.ChoiceField(choices=[r.value for r in webhooks.WebhookResult]),
    },
)


class PaymentWebhookView(APIView):
    """Receives payment status events from the (simulated) provider.

    Authenticated by an HMAC signature over the raw body instead of a user JWT. Any 2xx
    tells the provider to stop redelivering; non-2xx responses invite a retry.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "webhook"

    @extend_schema(
        tags=["payments"],
        request=webhooks.WebhookEnvelopeSerializer,
        parameters=[
            OpenApiParameter(
                webhooks.TIMESTAMP_HEADER, str, OpenApiParameter.HEADER, required=True
            ),
            OpenApiParameter(
                webhooks.SIGNATURE_HEADER,
                str,
                OpenApiParameter.HEADER,
                required=True,
                description='"sha256=" + hex HMAC-SHA256 of "{timestamp}.{raw body}".',
            ),
        ],
        responses={200: _WebhookResponse},
        auth=[],
    )
    def post(self, request):
        body = request.body  # raw bytes: the signature covers exactly what was sent
        webhooks.verify_signature(
            body=body,
            timestamp=request.headers.get(webhooks.TIMESTAMP_HEADER),
            signature=request.headers.get(webhooks.SIGNATURE_HEADER),
            secret=settings.PAYMENT_WEBHOOK_SECRET,
            tolerance_seconds=settings.PAYMENT_WEBHOOK_TOLERANCE_SECONDS,
        )
        payload = webhooks.parse_payload(body)
        event = webhooks.receive_event(payload)
        result = webhooks.process_event(event.pk)
        return Response({"event_id": event.event_id, "result": result.value})
