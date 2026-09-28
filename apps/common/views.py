import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.exception_handler import error_body

logger = logging.getLogger(__name__)

_HealthResponse = inline_serializer(
    name="HealthResponse",
    fields={"status": serializers.CharField(), "checks": serializers.DictField(required=False)},
)


@extend_schema(tags=["health"], responses={200: _HealthResponse})
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([])
def liveness(request):
    """The process is up and able to serve requests."""
    return Response({"status": "ok"})


@extend_schema(tags=["health"], responses={200: _HealthResponse, 503: _HealthResponse})
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([])
def readiness(request):
    """Dependencies (the database) are reachable."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.warning("readiness_check_failed", extra={"dependency": "database"})
        return Response(
            {"status": "unavailable", "checks": {"database": "unavailable"}}, status=503
        )
    return Response({"status": "ok", "checks": {"database": "ok"}})


def json_not_found(request, exception=None):
    """Django-level 404 (unmatched URLs) in the same envelope as API errors."""
    return JsonResponse(error_body("NOT_FOUND", "Resource not found."), status=404)


def json_server_error(request):
    return JsonResponse(error_body("INTERNAL_ERROR", "An unexpected error occurred."), status=500)
