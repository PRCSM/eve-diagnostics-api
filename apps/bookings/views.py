from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.bookings import services
from apps.bookings.serializers import (
    BookingCreateSerializer,
    BookingListQuerySerializer,
    BookingSerializer,
)


class BookingListCreateView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [OrderingFilter]
    ordering_fields = ["created_at", "appointment_at"]
    ordering = ["-created_at"]

    def get_queryset(self) -> QuerySet:
        params = BookingListQuerySerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        queryset = services.visible_bookings(self.request.user)
        if booking_status := params.validated_data.get("status"):
            queryset = queryset.filter(status=booking_status)
        return queryset

    @extend_schema(
        tags=["bookings"],
        parameters=[BookingListQuerySerializer],
        responses={200: BookingSerializer(many=True)},
    )
    def get(self, request):
        """Your bookings (staff: all bookings)."""
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(BookingSerializer(page, many=True).data)

    @extend_schema(
        tags=["bookings"], request=BookingCreateSerializer, responses={201: BookingSerializer}
    )
    def post(self, request):
        """Book a test at a centre. The booking starts PENDING until it is paid."""
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.create_booking(user=request.user, **serializer.validated_data)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)


class BookingDetailView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["bookings"], responses={200: BookingSerializer})
    def get(self, request, booking_id):
        booking = services.get_visible_booking(user=request.user, booking_id=booking_id)
        return Response(BookingSerializer(booking).data)


class BookingCancelView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["bookings"], request=None, responses={200: BookingSerializer})
    def post(self, request, booking_id):
        """Cancel one of your pending bookings. Repeating the call is safe."""
        booking = services.cancel_booking(user=request.user, booking_id=booking_id)
        return Response(BookingSerializer(booking).data)
