"""Act as the payment provider: build a correctly signed webhook for an existing payment.

Examples:
    python manage.py simulate_webhook sim_pay_abc123 --outcome succeeded
    python manage.py simulate_webhook sim_pay_abc123 --outcome succeeded --event-id evt_1 \\
        --send http://127.0.0.1:8000/api/v1/payments/webhook/ --repeat 3
"""

import json
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.payments.models import Payment
from apps.payments.webhooks import (
    PROVIDER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    compute_signature,
)


def build_event(payment: Payment, *, outcome: str, event_id: str, amount: str | None) -> dict:
    return {
        "event_id": event_id,
        "event_type": f"payment.{outcome}",
        "occurred_at": timezone.now().isoformat(),
        "data": {
            "payment_reference": payment.provider_reference,
            "booking_id": str(payment.booking_id),
            "amount": amount or str(payment.amount),
            "currency": payment.currency,
            "failure_reason": "Declined (simulated webhook)." if outcome == "failed" else None,
        },
    }


def signed_request(event: dict) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(event).encode()
    timestamp = str(int(time.time()))
    signature = compute_signature(
        secret=settings.PAYMENT_WEBHOOK_SECRET, timestamp=timestamp, body=body
    )
    headers = {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: signature,
    }
    return body, headers


class Command(BaseCommand):
    help = "Build (and optionally send) a signed payment webhook, as the provider would."

    def add_arguments(self, parser):
        parser.add_argument("payment_reference")
        parser.add_argument("--outcome", choices=["succeeded", "failed"], default="succeeded")
        parser.add_argument("--event-id", help="Reuse an id to simulate a duplicate delivery.")
        parser.add_argument("--amount", help="Override the amount (to test mismatch handling).")
        parser.add_argument("--send", metavar="URL", help="POST the webhook to this URL.")
        parser.add_argument("--repeat", type=int, default=1, help="Deliveries to send.")

    def handle(self, *args, **options):
        try:
            payment = Payment.objects.get(
                provider=PROVIDER, provider_reference=options["payment_reference"]
            )
        except Payment.DoesNotExist as exc:
            raise CommandError("No payment with that provider reference.") from exc

        event_id = options["event_id"] or f"evt_{uuid.uuid4().hex[:16]}"
        event = build_event(
            payment, outcome=options["outcome"], event_id=event_id, amount=options["amount"]
        )

        if not options["send"]:
            body, headers = signed_request(event)
            header_args = " ".join(f"-H '{name}: {value}'" for name, value in headers.items())
            self.stdout.write(
                "curl -X POST http://127.0.0.1:8000/api/v1/payments/webhook/ "
                f"{header_args} --data '{body.decode()}'"
            )
            return

        url = options["send"]
        if urlparse(url).scheme not in {"http", "https"}:
            raise CommandError("--send must be an http(s) URL.")
        for attempt in range(1, options["repeat"] + 1):
            body, headers = signed_request(event)  # fresh timestamp per delivery
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
            try:
                with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
                    status, text = response.status, response.read().decode()
            except urllib.error.HTTPError as exc:
                status, text = exc.code, exc.read().decode()
            self.stdout.write(f"delivery {attempt}: HTTP {status} {text}")
