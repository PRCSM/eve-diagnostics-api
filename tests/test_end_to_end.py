"""One complete patient journey through the public API, including a duplicated webhook."""

import pytest

from tests.conftest import future

pytestmark = pytest.mark.django_db


def test_patient_books_pays_asynchronously_and_webhook_confirms(api_client, send_webhook, offering):
    signup = api_client.post(
        "/api/v1/auth/signup/",
        {
            "email": "journey@example.com",
            "password": "a-long-passphrase-42",
            "full_name": "Journey Patient",
        },
    )
    assert signup.status_code == 201

    tokens = api_client.post(
        "/api/v1/auth/login/",
        {"email": "journey@example.com", "password": "a-long-passphrase-42"},
    ).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    centres = api_client.get("/api/v1/centres/", {"city": "Pune", "test": str(offering.test_id)})
    centre_id = centres.json()["results"][0]["id"]

    booking = api_client.post(
        "/api/v1/bookings/",
        {
            "centre_id": centre_id,
            "test_id": str(offering.test_id),
            "appointment_at": future().isoformat(),
        },
    ).json()
    assert (booking["status"], booking["amount"]) == ("PENDING", "499.00")

    payment = api_client.post(
        "/api/v1/payments/",
        {"booking_id": booking["id"], "simulate_outcome": "PENDING"},
        HTTP_IDEMPOTENCY_KEY="journey-checkout-1",
    ).json()
    assert payment["status"] == "PENDING"

    event = {
        "event_id": "evt_journey",
        "event_type": "payment.succeeded",
        "occurred_at": "2026-09-28T10:00:00Z",
        "data": {
            "payment_reference": payment["provider_reference"],
            "booking_id": booking["id"],
            "amount": payment["amount"],
            "currency": "INR",
        },
    }
    assert send_webhook(event).json()["result"] == "processed"
    assert send_webhook(event).json()["result"] == "duplicate"

    final = api_client.get(f"/api/v1/bookings/{booking['id']}/").json()
    assert final["status"] == "CONFIRMED"
    assert [p["status"] for p in final["payments"]] == ["SUCCESS"]
