import re

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.payments import services
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
