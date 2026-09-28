import json
import time
from decimal import Decimal
from unittest import mock

import pytest
from django.core.management import call_command

from apps.bookings.models import BookingStatus
from apps.payments.models import Payment, PaymentStatus, WebhookEvent, WebhookEventStatus
from tests.conftest import WEBHOOK_URL, signed_headers, webhook_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def pending_payment(booking, make_payment):
    return make_payment(booking, reference="sim_pay_pending")


def refreshed(*objects):
    for obj in objects:
        obj.refresh_from_db()


class TestAuthentication:
    def test_missing_signature_headers(self, send_webhook, pending_payment):
        response = send_webhook(webhook_event(pending_payment), headers={})

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_SIGNATURE"
        assert not WebhookEvent.objects.exists()

    def test_wrong_secret(self, send_webhook, pending_payment):
        response = send_webhook(webhook_event(pending_payment), secret="attacker-guess")

        assert response.status_code == 401
        refreshed(pending_payment)
        assert pending_payment.status == PaymentStatus.PENDING

    def test_tampered_body(self, send_webhook, pending_payment):
        original = json.dumps(webhook_event(pending_payment, event_type="payment.failed")).encode()
        forged = json.dumps(webhook_event(pending_payment, event_type="payment.succeeded")).encode()

        response = send_webhook(body=forged, headers=signed_headers(original))

        assert response.status_code == 401
        assert not WebhookEvent.objects.exists()

    def test_replayed_old_delivery(self, send_webhook, pending_payment):
        response = send_webhook(webhook_event(pending_payment), timestamp=int(time.time()) - 3600)

        assert response.status_code == 401
        assert "window" in response.json()["error"]["message"]

    def test_user_jwt_is_neither_needed_nor_sufficient(
        self, send_webhook, user_client, pending_payment
    ):
        body = webhook_event(pending_payment)

        assert user_client.post(WEBHOOK_URL, body).status_code == 401
        assert send_webhook(body).status_code == 200

    def test_get_is_not_allowed(self, api_client):
        assert api_client.get(WEBHOOK_URL).status_code == 405


class TestPayload:
    def test_invalid_json(self, send_webhook):
        response = send_webhook(body=b"{not json")

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_PAYLOAD"

    def test_missing_envelope_fields(self, send_webhook):
        response = send_webhook({"event_type": "payment.succeeded"})

        assert response.status_code == 400
        assert {"event_id", "occurred_at", "data"} <= set(response.json()["error"]["details"])

    def test_payment_event_requires_payment_data(self, send_webhook, pending_payment):
        payload = webhook_event(pending_payment)
        del payload["data"]["booking_id"]

        response = send_webhook(payload)

        assert response.status_code == 400
        assert "booking_id" in response.json()["error"]["details"]["data"]

    def test_body_size_is_capped(self, send_webhook):
        response = send_webhook(body=b'{"x":"' + b"a" * 300_000 + b'"}')

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


class TestProcessing:
    def test_succeeded_event_confirms_booking(self, send_webhook, pending_payment, booking):
        response = send_webhook(webhook_event(pending_payment))

        assert response.status_code == 200
        assert response.json() == {"event_id": "evt_0001", "result": "processed"}
        refreshed(pending_payment, booking)
        assert pending_payment.status == PaymentStatus.SUCCESS
        assert booking.status == BookingStatus.CONFIRMED
        event = WebhookEvent.objects.get()
        assert event.status == WebhookEventStatus.PROCESSED
        assert event.attempts == 1
        assert event.payment == pending_payment

    def test_failed_event_fails_booking(self, send_webhook, pending_payment, booking):
        payload = webhook_event(
            pending_payment, event_type="payment.failed", failure_reason="Insufficient funds"
        )

        response = send_webhook(payload)

        assert response.json()["result"] == "processed"
        refreshed(pending_payment, booking)
        assert pending_payment.status == PaymentStatus.FAILED
        assert pending_payment.failure_reason == "Insufficient funds"
        assert booking.status == BookingStatus.FAILED

    def test_unknown_event_type_is_acknowledged_and_ignored(self, send_webhook):
        payload = {
            "event_id": "evt_refund_1",
            "event_type": "refund.created",
            "occurred_at": "2026-09-28T10:00:00Z",
            "data": {"anything": "goes"},
        }

        response = send_webhook(payload)

        assert response.json()["result"] == "ignored"
        assert WebhookEvent.objects.get().status == WebhookEventStatus.IGNORED


class TestIdempotency:
    def test_repeated_delivery_is_applied_once(self, send_webhook, pending_payment, booking):
        payload = webhook_event(pending_payment)
        send_webhook(payload)
        refreshed(pending_payment)
        completed_at = pending_payment.completed_at

        responses = [send_webhook(payload) for _ in range(3)]

        assert [r.json()["result"] for r in responses] == ["duplicate"] * 3
        assert WebhookEvent.objects.count() == 1
        assert WebhookEvent.objects.get().attempts == 1
        refreshed(pending_payment, booking)
        assert pending_payment.completed_at == completed_at
        assert booking.status == BookingStatus.CONFIRMED

    def test_reserialised_payload_is_still_a_duplicate(self, send_webhook, pending_payment):
        payload = webhook_event(pending_payment)
        send_webhook(payload)
        reordered = json.dumps(payload, indent=2, sort_keys=True).encode()

        response = send_webhook(body=reordered)

        assert response.json()["result"] == "duplicate"

    def test_same_event_id_with_different_payload_is_rejected(
        self, send_webhook, pending_payment, booking
    ):
        send_webhook(webhook_event(pending_payment, event_type="payment.failed"))

        response = send_webhook(webhook_event(pending_payment, event_type="payment.succeeded"))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EVENT_ID_CONFLICT"
        refreshed(booking)
        assert booking.status == BookingStatus.FAILED

    def test_new_event_repeating_an_applied_outcome_is_a_no_op(
        self, user_client, send_webhook, booking
    ):
        paid = user_client.post(
            "/api/v1/payments/", {"booking_id": str(booking.id), "simulate_outcome": "SUCCESS"}
        ).json()
        payment = Payment.objects.get(id=paid["id"])

        response = send_webhook(webhook_event(payment, event_id="evt_late_confirmation"))

        assert response.json()["result"] == "processed"
        refreshed(booking)
        assert booking.status == BookingStatus.CONFIRMED

    def test_conflicting_outcome_does_not_corrupt_confirmed_booking(
        self, send_webhook, pending_payment, booking
    ):
        send_webhook(webhook_event(pending_payment, event_id="evt_ok"))

        response = send_webhook(
            webhook_event(pending_payment, event_id="evt_late_fail", event_type="payment.failed")
        )

        assert response.status_code == 200
        assert response.json()["result"] == "ignored"
        refreshed(pending_payment, booking)
        assert pending_payment.status == PaymentStatus.SUCCESS
        assert booking.status == BookingStatus.CONFIRMED
        event = WebhookEvent.objects.get(event_id="evt_late_fail")
        assert event.status == WebhookEventStatus.IGNORED
        assert "Conflicting result" in event.last_error


class TestFailuresAndRetries:
    def test_unknown_payment_reference_is_stored_for_retry(
        self, send_webhook, booking, make_payment
    ):
        payload = {
            "event_id": "evt_early",
            "event_type": "payment.succeeded",
            "occurred_at": "2026-09-28T10:00:00Z",
            "data": {
                "payment_reference": "sim_pay_not_yet_recorded",
                "booking_id": str(booking.id),
                "amount": "499.00",
                "currency": "INR",
            },
        }

        response = send_webhook(payload)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PAYMENT_NOT_FOUND"
        event = WebhookEvent.objects.get()
        assert (event.status, event.attempts) == (WebhookEventStatus.FAILED, 1)

        # The payment shows up later; the provider's redelivery now succeeds.
        make_payment(booking, reference="sim_pay_not_yet_recorded")
        retry = send_webhook(payload)

        assert retry.json()["result"] == "processed"
        event.refresh_from_db()
        assert (event.status, event.attempts) == (WebhookEventStatus.PROCESSED, 2)

    @pytest.mark.parametrize(
        "override, field",
        [
            ({"amount": "1.00"}, "amount"),
            ({"currency": "USD"}, "currency"),
            ({"booking_id": "00000000-0000-0000-0000-000000000000"}, "booking_id"),
        ],
    )
    def test_mismatched_data_is_not_applied(
        self, send_webhook, pending_payment, booking, override, field
    ):
        response = send_webhook(webhook_event(pending_payment, **override))

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "PAYLOAD_MISMATCH"
        assert error["details"]["fields"] == [field]
        refreshed(pending_payment, booking)
        assert pending_payment.status == PaymentStatus.PENDING
        assert booking.status == BookingStatus.PENDING
        assert WebhookEvent.objects.get().status == WebhookEventStatus.FAILED

    def test_unexpected_error_returns_500_and_redelivery_recovers(
        self, send_webhook, pending_payment, booking
    ):
        payload = webhook_event(pending_payment)
        with mock.patch(
            "apps.payments.webhooks.apply_payment_result", side_effect=RuntimeError("db hiccup")
        ):
            response = send_webhook(payload)

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        event = WebhookEvent.objects.get()
        assert event.status == WebhookEventStatus.FAILED
        assert "RuntimeError" in event.last_error
        refreshed(booking)
        assert booking.status == BookingStatus.PENDING

        assert send_webhook(payload).json()["result"] == "processed"
        refreshed(booking)
        assert booking.status == BookingStatus.CONFIRMED

    def test_retry_command_processes_failed_events(self, send_webhook, booking, make_payment):
        payload = {
            "event_id": "evt_retry_me",
            "event_type": "payment.failed",
            "occurred_at": "2026-09-28T10:00:00Z",
            "data": {
                "payment_reference": "sim_pay_late",
                "booking_id": str(booking.id),
                "amount": "499.00",
                "currency": "INR",
            },
        }
        send_webhook(payload)
        make_payment(booking, reference="sim_pay_late")

        call_command("retry_webhook_events")

        event = WebhookEvent.objects.get()
        assert event.status == WebhookEventStatus.PROCESSED
        refreshed(booking)
        assert booking.status == BookingStatus.FAILED

    def test_retry_command_respects_max_attempts(self, send_webhook, pending_payment):
        payload = webhook_event(pending_payment, amount="1.00")
        send_webhook(payload)
        WebhookEvent.objects.update(attempts=5)

        call_command("retry_webhook_events", "--max-attempts", "5")

        assert WebhookEvent.objects.get().attempts == 5


def test_simulate_webhook_command_prints_signed_request(pending_payment, capsys):
    call_command("simulate_webhook", "sim_pay_pending", "--event-id", "evt_cli")

    output = capsys.readouterr().out
    assert "X-Webhook-Signature: sha256=" in output
    assert '"event_id": "evt_cli"' in output
    assert Decimal(json.loads(output.split("--data '")[1].rstrip("'\n"))["data"]["amount"]) == (
        pending_payment.amount
    )
