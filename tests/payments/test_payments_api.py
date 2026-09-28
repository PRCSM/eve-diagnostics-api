from datetime import timedelta
from unittest import mock

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.payments.gateway import GatewayError
from apps.payments.models import Payment, PaymentStatus

pytestmark = pytest.mark.django_db

PAYMENTS_URL = "/api/v1/payments/"


def pay(client, booking, outcome: str | None = "SUCCESS", key: str | None = None, **extra):
    body = {"booking_id": str(booking.id), **extra}
    if outcome is not None:
        body["simulate_outcome"] = outcome
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
    return client.post(PAYMENTS_URL, body, **headers)


class TestSimulatedPayment:
    def test_success_confirms_booking(self, user_client, booking):
        response = pay(user_client, booking, "SUCCESS")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "SUCCESS"
        assert body["booking_status"] == "CONFIRMED"
        assert body["amount"] == "499.00"
        assert body["provider_reference"].startswith("sim_pay_")
        assert body["completed_at"] is not None
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED

    def test_failure_fails_booking(self, user_client, booking):
        response = pay(user_client, booking, "FAILED")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "FAILED"
        assert body["booking_status"] == "FAILED"
        assert body["failure_reason"]
        booking.refresh_from_db()
        assert booking.status == BookingStatus.FAILED

    def test_pending_waits_for_webhook(self, user_client, booking):
        response = pay(user_client, booking, "PENDING")

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "PENDING"
        assert body["booking_status"] == "PENDING"
        assert body["completed_at"] is None

    def test_default_outcome_comes_from_settings(self, user_client, booking, settings):
        settings.PAYMENT_SIMULATION_DEFAULT_OUTCOME = "FAILED"

        response = pay(user_client, booking, outcome=None)

        assert response.json()["status"] == "FAILED"

    def test_amount_always_comes_from_booking(self, user_client, booking):
        response = pay(user_client, booking, "SUCCESS", amount="1.00")

        assert response.json()["amount"] == "499.00"
        assert Payment.objects.get().amount == booking.amount

    def test_invalid_outcome(self, user_client, booking):
        response = pay(user_client, booking, "MAYBE")

        assert response.status_code == 400
        assert "simulate_outcome" in response.json()["error"]["details"]

    def test_booking_detail_lists_payments(self, user_client, booking):
        payment_id = pay(user_client, booking, "FAILED").json()["id"]

        detail = user_client.get(f"/api/v1/bookings/{booking.id}/").json()

        assert [p["id"] for p in detail["payments"]] == [payment_id]


class TestInvalidPayments:
    @pytest.mark.parametrize(
        "status", [BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED]
    )
    def test_booking_not_pending(self, user_client, user, make_booking, status):
        booking = make_booking(user, status=status)

        response = pay(user_client, booking)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "BOOKING_NOT_PAYABLE"
        assert not Payment.objects.exists()

    def test_cannot_pay_twice(self, user_client, booking):
        pay(user_client, booking, "SUCCESS")

        response = pay(user_client, booking, "SUCCESS")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "BOOKING_NOT_PAYABLE"
        assert Payment.objects.count() == 1

    def test_appointment_in_the_past(self, user_client, booking):
        Booking.objects.filter(pk=booking.pk).update(
            appointment_at=timezone.now() - timedelta(minutes=1)
        )

        response = pay(user_client, booking)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "BOOKING_NOT_PAYABLE"

    def test_second_attempt_while_one_is_pending(self, user_client, booking):
        pay(user_client, booking, "PENDING")

        response = pay(user_client, booking, "SUCCESS")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PAYMENT_IN_PROGRESS"

    def test_someone_elses_booking(self, other_client, booking):
        response = pay(other_client, booking)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "BOOKING_NOT_FOUND"
        booking.refresh_from_db()
        assert booking.status == BookingStatus.PENDING

    def test_unknown_booking(self, user_client):
        response = user_client.post(
            PAYMENTS_URL, {"booking_id": "00000000-0000-0000-0000-000000000000"}
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "BOOKING_NOT_FOUND"

    @pytest.mark.parametrize("body", [{}, {"booking_id": "123"}, {"booking_id": None}])
    def test_malformed_request(self, user_client, body):
        response = user_client.post(PAYMENTS_URL, body)

        assert response.status_code == 400
        assert "booking_id" in response.json()["error"]["details"]

    def test_requires_authentication(self, api_client, booking):
        assert pay(api_client, booking).status_code == 401

    def test_cannot_cancel_while_payment_pending(self, user_client, booking):
        pay(user_client, booking, "PENDING")

        response = user_client.post(f"/api/v1/bookings/{booking.id}/cancel/")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PAYMENT_IN_PROGRESS"


class TestIdempotencyKey:
    def test_retry_returns_original_payment(self, user_client, booking):
        first = pay(user_client, booking, "SUCCESS", key="order-123-attempt-1")

        retry = pay(user_client, booking, "SUCCESS", key="order-123-attempt-1")

        assert first.status_code == 201
        assert retry.status_code == 200
        assert retry.json()["id"] == first.json()["id"]
        assert Payment.objects.count() == 1

    def test_same_key_different_request(self, user_client, booking):
        pay(user_client, booking, "PENDING", key="key-1")

        response = pay(user_client, booking, "SUCCESS", key="key-1")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    def test_new_key_after_success_is_still_rejected(self, user_client, booking):
        pay(user_client, booking, "SUCCESS", key="key-1")

        response = pay(user_client, booking, "SUCCESS", key="key-2")

        assert response.status_code == 409

    def test_key_is_scoped_to_the_booking(self, user_client, user, make_booking, booking):
        other_booking = make_booking(user, appointment_at=booking.appointment_at + timedelta(1))
        pay(user_client, booking, "SUCCESS", key="shared")

        response = pay(user_client, other_booking, "SUCCESS", key="shared")

        assert response.status_code == 201

    @pytest.mark.parametrize("key", ["has space", "x" * 256, ""])
    def test_invalid_key(self, user_client, booking, key):
        response = pay(user_client, booking, key=key)

        assert response.status_code == 400
        assert "Idempotency-Key" in response.json()["error"]["details"]


class TestGatewayFailure:
    def test_gateway_error_leaves_payment_pending(self, user_client, booking):
        with mock.patch(
            "apps.payments.gateway.SimulatedGateway.charge", side_effect=GatewayError("down")
        ):
            response = pay(user_client, booking, "SUCCESS")

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "GATEWAY_ERROR"
        payment = Payment.objects.get()
        assert payment.status == PaymentStatus.PENDING
        booking.refresh_from_db()
        assert booking.status == BookingStatus.PENDING


class TestReadPayment:
    def test_owner_and_staff_can_read(self, user_client, admin_client, booking):
        payment_id = pay(user_client, booking).json()["id"]

        assert user_client.get(f"{PAYMENTS_URL}{payment_id}/").status_code == 200
        assert admin_client.get(f"{PAYMENTS_URL}{payment_id}/").status_code == 200

    def test_other_user_gets_404(self, user_client, other_client, booking):
        payment_id = pay(user_client, booking).json()["id"]

        response = other_client.get(f"{PAYMENTS_URL}{payment_id}/")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PAYMENT_NOT_FOUND"


class TestDatabaseConstraints:
    def test_only_one_successful_payment_per_booking(self, booking, make_payment):
        make_payment(booking, status=PaymentStatus.SUCCESS)

        with pytest.raises(IntegrityError), transaction.atomic():
            make_payment(booking, status=PaymentStatus.SUCCESS)

    def test_only_one_pending_payment_per_booking(self, booking, make_payment):
        make_payment(booking)

        with pytest.raises(IntegrityError), transaction.atomic():
            make_payment(booking)

    def test_failed_attempts_do_not_block_each_other(self, booking, make_payment):
        make_payment(booking, status=PaymentStatus.FAILED)
        make_payment(booking, status=PaymentStatus.FAILED)

        assert booking.payments.count() == 2

    def test_completed_at_must_match_status(self, booking, make_payment):
        payment = make_payment(booking)

        with pytest.raises(IntegrityError), transaction.atomic():
            Payment.objects.filter(pk=payment.pk).update(status=PaymentStatus.SUCCESS)
