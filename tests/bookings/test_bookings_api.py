from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from tests.conftest import future

pytestmark = pytest.mark.django_db

BOOKINGS_URL = "/api/v1/bookings/"


def booking_url(booking_id) -> str:
    return f"{BOOKINGS_URL}{booking_id}/"


def cancel_url(booking_id) -> str:
    return f"{BOOKINGS_URL}{booking_id}/cancel/"


def payload(offering, **overrides) -> dict:
    body = {
        "centre_id": str(offering.centre_id),
        "test_id": str(offering.test_id),
        "appointment_at": future().isoformat(),
    }
    body.update(overrides)
    return body


class TestCreateBooking:
    def test_creates_pending_booking_with_server_side_amount(self, user_client, user, offering):
        response = user_client.post(
            BOOKINGS_URL, payload(offering, amount="1.00", status="CONFIRMED")
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "PENDING"
        assert body["amount"] == "499.00"
        assert body["currency"] == "INR"
        assert body["user_id"] == str(user.id)
        assert body["centre"] == {
            "id": str(offering.centre_id),
            "name": "Sample Diagnostics Baner",
            "city": "Pune",
        }
        assert body["test"]["code"] == "CBC"

    def test_amount_is_a_snapshot(self, user_client, offering):
        booking_id = user_client.post(BOOKINGS_URL, payload(offering)).json()["id"]
        offering.price = Decimal("999.00")
        offering.save()

        assert user_client.get(booking_url(booking_id)).json()["amount"] == "499.00"

    def test_accepts_other_timezone_offsets(self, user_client, offering):
        appointment = future().astimezone(timezone.get_fixed_timezone(-300))

        response = user_client.post(
            BOOKINGS_URL, payload(offering, appointment_at=appointment.isoformat())
        )

        assert response.status_code == 201
        stored = Booking.objects.get(id=response.json()["id"]).appointment_at
        assert stored == appointment

    @pytest.mark.parametrize(
        "appointment_at, message",
        [
            ((timezone.now() - timedelta(hours=1)).isoformat(), "future"),
            ((timezone.now() + timedelta(days=91)).isoformat(), "within 90 days"),
            ("2026-12-01T09:30:00", "timezone offset"),
            ("next tuesday", "format"),
        ],
    )
    def test_invalid_appointment_time(self, user_client, offering, appointment_at, message):
        response = user_client.post(BOOKINGS_URL, payload(offering, appointment_at=appointment_at))

        assert response.status_code == 400
        errors = response.json()["error"]["details"]["appointment_at"]
        assert message in errors[0]

    def test_missing_fields(self, user_client):
        response = user_client.post(BOOKINGS_URL, {})

        assert response.status_code == 400
        assert set(response.json()["error"]["details"]) == {
            "centre_id",
            "test_id",
            "appointment_at",
        }

    def test_malformed_ids(self, user_client, offering):
        response = user_client.post(BOOKINGS_URL, payload(offering, centre_id="abc"))

        assert response.status_code == 400
        assert "centre_id" in response.json()["error"]["details"]

    def test_test_not_offered_at_centre(self, user_client, offering):
        response = user_client.post(
            BOOKINGS_URL, payload(offering, test_id="00000000-0000-0000-0000-000000000000")
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "OFFERING_NOT_FOUND"

    @pytest.mark.parametrize("inactive", ["offering", "centre", "test"])
    def test_inactive_catalog_items_are_not_bookable(self, user_client, offering, inactive):
        target = {"offering": offering, "centre": offering.centre, "test": offering.test}[inactive]
        target.is_active = False
        target.save()

        response = user_client.post(BOOKINGS_URL, payload(offering))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "OFFERING_NOT_FOUND"

    def test_duplicate_active_booking_is_rejected(self, user_client, offering):
        body = payload(offering)
        first = user_client.post(BOOKINGS_URL, body)

        second = user_client.post(BOOKINGS_URL, body)

        assert second.status_code == 409
        assert second.json()["error"]["code"] == "DUPLICATE_BOOKING"
        user_client.post(cancel_url(first.json()["id"]))
        assert user_client.post(BOOKINGS_URL, body).status_code == 201

    def test_requires_authentication(self, api_client, offering):
        response = api_client.post(BOOKINGS_URL, payload(offering))

        assert response.status_code == 401


class TestReadBookings:
    def test_list_shows_only_own_bookings(self, user_client, user, other_user, make_booking):
        mine = make_booking(user)
        make_booking(other_user)

        response = user_client.get(BOOKINGS_URL)

        assert [b["id"] for b in response.json()["results"]] == [str(mine.id)]

    def test_staff_see_all_bookings(self, admin_client, user, other_user, make_booking):
        make_booking(user)
        make_booking(other_user)

        assert admin_client.get(BOOKINGS_URL).json()["count"] == 2

    def test_filter_by_status(self, user_client, user, make_booking):
        make_booking(user)
        confirmed = make_booking(user, status=BookingStatus.CONFIRMED, appointment_at=future(4))

        response = user_client.get(BOOKINGS_URL, {"status": "CONFIRMED"})

        assert [b["id"] for b in response.json()["results"]] == [str(confirmed.id)]

    def test_invalid_status_filter(self, user_client):
        response = user_client.get(BOOKINGS_URL, {"status": "PAID"})

        assert response.status_code == 400

    def test_list_query_count_is_bounded(
        self, user_client, user, make_booking, django_assert_max_num_queries
    ):
        for day in range(1, 8):
            make_booking(user, appointment_at=future(day))

        with django_assert_max_num_queries(4):
            response = user_client.get(BOOKINGS_URL)

        assert response.json()["count"] == 7

    def test_other_users_booking_is_not_found(self, other_client, booking):
        response = other_client.get(booking_url(booking.id))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "BOOKING_NOT_FOUND"

    def test_unknown_booking_is_not_found(self, user_client):
        response = user_client.get(booking_url("00000000-0000-0000-0000-000000000000"))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "BOOKING_NOT_FOUND"

    def test_staff_can_read_any_booking(self, admin_client, booking):
        assert admin_client.get(booking_url(booking.id)).status_code == 200

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_bookings_cannot_be_modified_directly(self, user_client, booking, method):
        response = getattr(user_client, method)(booking_url(booking.id), {"status": "CONFIRMED"})

        assert response.status_code == 405
        booking.refresh_from_db()
        assert booking.status == BookingStatus.PENDING


class TestCancelBooking:
    def test_cancel_pending_booking(self, user_client, booking):
        response = user_client.post(cancel_url(booking.id))

        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"

    def test_cancel_is_idempotent(self, user_client, booking):
        user_client.post(cancel_url(booking.id))

        response = user_client.post(cancel_url(booking.id))

        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"

    @pytest.mark.parametrize("status", [BookingStatus.CONFIRMED, BookingStatus.FAILED])
    def test_cannot_cancel_settled_booking(self, user_client, user, make_booking, status):
        settled = make_booking(user, status=status)

        response = user_client.post(cancel_url(settled.id))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "BOOKING_NOT_CANCELLABLE"

    def test_cannot_cancel_someone_elses_booking(self, other_client, admin_client, booking):
        assert other_client.post(cancel_url(booking.id)).status_code == 404
        # Staff can read every booking, but only the owner can act on it.
        assert admin_client.post(cancel_url(booking.id)).status_code == 404
        booking.refresh_from_db()
        assert booking.status == BookingStatus.PENDING


class TestDatabaseConstraints:
    def test_invalid_status_is_rejected(self, booking):
        with pytest.raises(IntegrityError), transaction.atomic():
            Booking.objects.filter(pk=booking.pk).update(status="PAID")

    def test_duplicate_active_booking_is_rejected(self, booking):
        with pytest.raises(IntegrityError), transaction.atomic():
            Booking.objects.create(
                user=booking.user,
                offering=booking.offering,
                appointment_at=booking.appointment_at,
                amount=booking.amount,
            )

    def test_amount_must_be_positive(self, booking):
        with pytest.raises(IntegrityError), transaction.atomic():
            Booking.objects.filter(pk=booking.pk).update(amount=Decimal("0"))
