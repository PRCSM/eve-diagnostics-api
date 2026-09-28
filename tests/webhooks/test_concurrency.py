"""Concurrency: duplicates arriving at the same moment, not just one after another.

These use real transactions (transaction=True) and one DB connection per thread, so the
row locks and unique constraints are exercised exactly as in production.
"""

import json
import threading
from collections import Counter
from decimal import Decimal

import pytest
from django.db import connection
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.bookings.models import Booking, BookingStatus
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest
from apps.payments.models import Payment, PaymentStatus, WebhookEvent
from tests.conftest import WEBHOOK_URL, future, signed_headers, webhook_event

pytestmark = pytest.mark.django_db(transaction=True)

THREADS = 6


def run_concurrently(target, count: int = THREADS) -> list:
    """Start `count` threads that call `target()` at (nearly) the same instant."""
    barrier = threading.Barrier(count)
    results: list = []
    lock = threading.Lock()

    def worker():
        try:
            barrier.wait()
            outcome = target()
            with lock:
                results.append(outcome)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == count, "a worker thread failed or hung"
    return results


@pytest.fixture
def pending_booking():
    user = User.objects.create_user(
        email="race@example.com", password="Str0ng-pass-phrase!", full_name="Race"
    )
    centre = DiagnosticCentre.objects.create(
        name="Race Centre", address="x", city="Pune", pincode="411001"
    )
    test = DiagnosticTest.objects.create(code="RACE", name="Race Test")
    offering = CentreTest.objects.create(centre=centre, test=test, price=Decimal("250.00"))
    return Booking.objects.create(
        user=user, offering=offering, appointment_at=future(), amount=offering.price
    )


def test_simultaneous_duplicate_webhooks_apply_exactly_once(pending_booking):
    payment = Payment.objects.create(
        booking=pending_booking,
        amount=pending_booking.amount,
        currency="INR",
        provider="simulated",
        provider_reference="sim_pay_race",
        request_hash="0" * 64,
    )
    body = json.dumps(webhook_event(payment, event_id="evt_race")).encode()

    def deliver():
        client = APIClient()
        response = client.generic(
            "POST", WEBHOOK_URL, body, content_type="application/json", **signed_headers(body)
        )
        return response.status_code, response.json()["result"]

    results = run_concurrently(deliver)

    assert Counter(results) == {(200, "processed"): 1, (200, "duplicate"): THREADS - 1}
    assert WebhookEvent.objects.count() == 1
    payment.refresh_from_db()
    pending_booking.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert pending_booking.status == BookingStatus.CONFIRMED


def _pay_client(booking: Booking) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(booking.user)}")
    return client


def test_simultaneous_payment_attempts_create_one_payment(pending_booking):
    def attempt():
        response = _pay_client(pending_booking).post(
            "/api/v1/payments/",
            {"booking_id": str(pending_booking.id), "simulate_outcome": "PENDING"},
        )
        return response.status_code

    results = run_concurrently(attempt)

    assert Counter(results) == {201: 1, 409: THREADS - 1}
    assert Payment.objects.filter(booking=pending_booking).count() == 1


def test_simultaneous_retries_with_same_idempotency_key(pending_booking):
    def attempt():
        response = _pay_client(pending_booking).post(
            "/api/v1/payments/",
            {"booking_id": str(pending_booking.id), "simulate_outcome": "SUCCESS"},
            HTTP_IDEMPOTENCY_KEY="checkout-42",
        )
        return response.status_code, response.json()["id"]

    results = run_concurrently(attempt)

    assert Counter(status for status, _ in results) == {201: 1, 200: THREADS - 1}
    assert len({payment_id for _, payment_id in results}) == 1
    pending_booking.refresh_from_db()
    assert pending_booking.status == BookingStatus.CONFIRMED
