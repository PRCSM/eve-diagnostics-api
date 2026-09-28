"""Payment provider boundary.

`PaymentGateway` is what the service layer depends on; `SimulatedGateway` is the only
implementation. A real provider (Razorpay, Stripe, ...) would be one more class here.
"""

import secrets
from dataclasses import dataclass
from typing import Protocol

from apps.payments.models import Payment, PaymentStatus, SimulatedOutcome


class GatewayError(Exception):
    """The provider was unreachable or returned something unusable."""


@dataclass(frozen=True)
class GatewayResult:
    reference: str
    status: str  # a PaymentStatus value; PENDING means "result will arrive by webhook"
    failure_reason: str = ""


class PaymentGateway(Protocol):
    name: str

    def charge(self, payment: Payment, *, simulate_outcome: str) -> GatewayResult: ...


class SimulatedGateway:
    name = "simulated"

    def charge(self, payment: Payment, *, simulate_outcome: str) -> GatewayResult:
        reference = f"sim_pay_{secrets.token_hex(12)}"
        if simulate_outcome == SimulatedOutcome.SUCCESS:
            return GatewayResult(reference=reference, status=PaymentStatus.SUCCESS)
        if simulate_outcome == SimulatedOutcome.FAILED:
            return GatewayResult(
                reference=reference,
                status=PaymentStatus.FAILED,
                failure_reason="Payment declined by issuer (simulated).",
            )
        return GatewayResult(reference=reference, status=PaymentStatus.PENDING)


def get_gateway() -> PaymentGateway:
    return SimulatedGateway()
