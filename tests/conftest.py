import itertools
import json
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.bookings.models import Booking, BookingStatus
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest
from apps.payments.models import Payment, PaymentStatus
from apps.payments.webhooks import compute_signature

WEBHOOK_URL = "/api/v1/payments/webhook/"

DEFAULT_PASSWORD = "Str0ng-pass-phrase!"
_email_counter = itertools.count(1)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters live in the cache; start every test with a clean slate."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(email: str | None = None, password: str = DEFAULT_PASSWORD, **extra) -> User:
        email = email or f"user{next(_email_counter)}@example.com"
        extra.setdefault("full_name", "Test Patient")
        return User.objects.create_user(email=email, password=password, **extra)

    return _make


@pytest.fixture
def user(make_user) -> User:
    return make_user(email="patient@example.com")


@pytest.fixture
def other_user(make_user) -> User:
    return make_user(email="other@example.com")


@pytest.fixture
def admin_user(make_user) -> User:
    return make_user(email="admin@example.com", is_staff=True)


@pytest.fixture
def client_for():
    """Build an APIClient authenticated with a real JWT for the given user."""

    def _client(user: User) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
        return client

    return _client


@pytest.fixture
def user_client(client_for, user) -> APIClient:
    return client_for(user)


@pytest.fixture
def other_client(client_for, other_user) -> APIClient:
    return client_for(other_user)


@pytest.fixture
def admin_client(client_for, admin_user) -> APIClient:
    return client_for(admin_user)


# --- Catalog ----------------------------------------------------------------------------------


@pytest.fixture
def centre(db) -> DiagnosticCentre:
    return DiagnosticCentre.objects.create(
        name="Sample Diagnostics Baner", address="12 Baner Road", city="Pune", pincode="411045"
    )


@pytest.fixture
def diagnostic_test(db) -> DiagnosticTest:
    return DiagnosticTest.objects.create(code="CBC", name="Complete Blood Count")


@pytest.fixture
def offering(centre, diagnostic_test) -> CentreTest:
    return CentreTest.objects.create(centre=centre, test=diagnostic_test, price=Decimal("499.00"))


# --- Bookings ---------------------------------------------------------------------------------


def future(days: int = 3, hour: int = 9) -> datetime:
    """A timezone-aware time `days` from now, on the hour."""
    return (timezone.now() + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


@pytest.fixture
def make_booking(offering):
    def _make(
        user: User,
        *,
        status: str = BookingStatus.PENDING,
        appointment_at: datetime | None = None,
        offering_: CentreTest | None = None,
    ) -> Booking:
        chosen = offering_ or offering
        return Booking.objects.create(
            user=user,
            offering=chosen,
            appointment_at=appointment_at or future(),
            amount=chosen.price,
            status=status,
        )

    return _make


@pytest.fixture
def booking(make_booking, user) -> Booking:
    return make_booking(user)


# --- Payments ---------------------------------------------------------------------------------


@pytest.fixture
def make_payment(db):
    def _make(
        booking: Booking,
        *,
        status: str = PaymentStatus.PENDING,
        reference: str | None = None,
    ) -> Payment:
        return Payment.objects.create(
            booking=booking,
            amount=booking.amount,
            currency=booking.currency,
            provider="simulated",
            provider_reference=reference or f"sim_pay_{uuid.uuid4().hex[:24]}",
            request_hash="0" * 64,
            status=status,
            completed_at=None if status == PaymentStatus.PENDING else timezone.now(),
        )

    return _make


# --- Webhooks ---------------------------------------------------------------------------------


def webhook_event(
    payment: Payment,
    *,
    event_id: str = "evt_0001",
    event_type: str = "payment.succeeded",
    **data_overrides,
) -> dict:
    data = {
        "payment_reference": payment.provider_reference,
        "booking_id": str(payment.booking_id),
        "amount": str(payment.amount),
        "currency": payment.currency,
        "failure_reason": None,
    }
    data.update(data_overrides)
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": timezone.now().isoformat(),
        "data": data,
    }


def signed_headers(body: bytes, *, secret: str | None = None, timestamp: int | None = None):
    ts = str(int(time.time()) if timestamp is None else timestamp)
    signature = compute_signature(
        secret=secret or settings.PAYMENT_WEBHOOK_SECRET, timestamp=ts, body=body
    )
    return {"HTTP_X_WEBHOOK_TIMESTAMP": ts, "HTTP_X_WEBHOOK_SIGNATURE": signature}


@pytest.fixture
def send_webhook(api_client):
    """POST a correctly signed webhook (override pieces to test the failure paths)."""

    def _send(payload: dict | None = None, *, body: bytes | None = None, headers=None, **sign):
        raw = body if body is not None else json.dumps(payload).encode()
        return api_client.generic(
            "POST",
            WEBHOOK_URL,
            raw,
            content_type="application/json",
            **(headers if headers is not None else signed_headers(raw, **sign)),
        )

    return _send
