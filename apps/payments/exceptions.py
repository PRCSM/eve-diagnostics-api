from apps.common.exceptions import (
    AuthenticationError,
    BadGatewayError,
    ConflictError,
    DomainError,
    NotFoundError,
    UnprocessableError,
)


class PaymentNotFound(NotFoundError):
    code = "PAYMENT_NOT_FOUND"
    default_message = "Payment not found."


class IdempotencyKeyReused(UnprocessableError):
    code = "IDEMPOTENCY_KEY_REUSED"
    default_message = "This Idempotency-Key was already used with a different request."


class PaymentGatewayUnavailable(BadGatewayError):
    code = "GATEWAY_ERROR"
    default_message = (
        "The payment provider did not respond. The payment is pending and will be settled "
        "when the provider reports its status."
    )


class InvalidWebhookSignature(AuthenticationError):
    code = "INVALID_SIGNATURE"
    default_message = "Webhook signature is missing, invalid or expired."


class InvalidWebhookPayload(DomainError):
    status_code = 400
    code = "INVALID_PAYLOAD"
    default_message = "Webhook payload is malformed."


class EventIdConflict(ConflictError):
    code = "EVENT_ID_CONFLICT"
    default_message = "This event_id was already received with a different payload."


class WebhookPayloadMismatch(UnprocessableError):
    code = "PAYLOAD_MISMATCH"
    default_message = "Webhook data does not match the payment on record."
