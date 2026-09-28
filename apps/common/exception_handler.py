"""Map every API exception to one error envelope:

{"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}
"""

import logging
import math
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import set_rollback
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.common.exceptions import DomainError
from apps.common.request_context import current_request_id

logger = logging.getLogger(__name__)

# Order matters: subclasses must come before their parents (InvalidToken < AuthenticationFailed).
_DRF_ERROR_CODES: list[tuple[type[drf_exceptions.APIException], str, str | None]] = [
    (drf_exceptions.ValidationError, "VALIDATION_ERROR", "Request validation failed."),
    (drf_exceptions.ParseError, "VALIDATION_ERROR", None),
    (drf_exceptions.NotAuthenticated, "NOT_AUTHENTICATED", None),
    (InvalidToken, "TOKEN_INVALID", "Token is invalid or expired."),
    (drf_exceptions.AuthenticationFailed, "AUTHENTICATION_FAILED", None),
    (drf_exceptions.PermissionDenied, "PERMISSION_DENIED", None),
    (drf_exceptions.NotFound, "NOT_FOUND", "Resource not found."),
    (drf_exceptions.MethodNotAllowed, "METHOD_NOT_ALLOWED", None),
    (drf_exceptions.NotAcceptable, "NOT_ACCEPTABLE", None),
    (drf_exceptions.UnsupportedMediaType, "UNSUPPORTED_MEDIA_TYPE", None),
    (drf_exceptions.Throttled, "RATE_LIMITED", "Too many requests. Please retry later."),
]


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": current_request_id(),
        }
    }


def _lookup_code(exc: drf_exceptions.APIException) -> tuple[str, str | None]:
    for exc_type, code, fixed_message in _DRF_ERROR_CODES:
        if isinstance(exc, exc_type):
            return code, fixed_message
    return str(exc.default_code).upper(), None


def _describe_api_exception(exc: drf_exceptions.APIException) -> tuple[str, str, Any]:
    code, fixed_message = _lookup_code(exc)

    details: Any = {}
    if isinstance(exc, drf_exceptions.ValidationError):
        details = exc.detail if isinstance(exc.detail, dict) else {"non_field_errors": exc.detail}
    elif isinstance(exc, drf_exceptions.Throttled) and exc.wait is not None:
        details = {"retry_after_seconds": math.ceil(exc.wait)}

    message = fixed_message or str(exc.detail)
    return code, message, details


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    if isinstance(exc, DomainError):
        set_rollback()
        return Response(error_body(exc.code, exc.message, exc.details), status=exc.status_code)

    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    if isinstance(exc, drf_exceptions.APIException):
        code, message, details = _describe_api_exception(exc)
        headers: dict[str, str] = {}
        auth_header = getattr(exc, "auth_header", None)
        if auth_header:
            headers["WWW-Authenticate"] = auth_header
        if isinstance(exc, drf_exceptions.Throttled) and exc.wait is not None:
            headers["Retry-After"] = str(math.ceil(exc.wait))
        set_rollback()
        return Response(error_body(code, message, details), status=exc.status_code, headers=headers)

    # Anything else is a bug: log it with the traceback, return a generic message.
    view = context.get("view")
    logger.exception(
        "unhandled_exception",
        extra={"view": type(view).__name__ if view is not None else None},
    )
    set_rollback()
    return Response(
        error_body("INTERNAL_ERROR", "An unexpected error occurred."),
        status=500,
    )
