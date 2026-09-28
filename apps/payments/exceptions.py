from apps.common.exceptions import BadGatewayError, NotFoundError, UnprocessableError


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
