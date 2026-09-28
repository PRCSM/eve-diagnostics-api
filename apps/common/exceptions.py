"""Domain errors raised by the service layer.

Services raise these instead of HTTP exceptions; the API exception handler maps them to the
standard error envelope. Each subclass carries a stable machine-readable `code`.
"""

from typing import Any


class DomainError(Exception):
    status_code = 400
    code = "DOMAIN_ERROR"
    default_message = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(DomainError):
    status_code = 404
    code = "NOT_FOUND"
    default_message = "Resource not found."


class ConflictError(DomainError):
    status_code = 409
    code = "CONFLICT"
    default_message = "The request conflicts with the current state of the resource."


class UnprocessableError(DomainError):
    status_code = 422
    code = "UNPROCESSABLE"
    default_message = "The request is well-formed but cannot be processed."


class AuthenticationError(DomainError):
    status_code = 401
    code = "AUTHENTICATION_FAILED"
    default_message = "Authentication failed."


class BadGatewayError(DomainError):
    status_code = 502
    code = "BAD_GATEWAY"
    default_message = "An upstream service failed."
