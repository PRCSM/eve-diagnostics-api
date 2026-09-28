from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest

pytestmark = pytest.mark.django_db

CENTRES_URL = "/api/v1/centres/"
TESTS_URL = "/api/v1/tests/"


def centre_url(centre_id) -> str:
    return f"{CENTRES_URL}{centre_id}/"


def offerings_url(centre_id) -> str:
    return f"{CENTRES_URL}{centre_id}/tests/"


def offering_url(centre_id, test_id) -> str:
    return f"{CENTRES_URL}{centre_id}/tests/{test_id}/"


CENTRE_PAYLOAD = {
    "name": "New Centre",
    "address": "1 Main Street",
    "city": "Pune",
    "pincode": "411001",
}


class TestPublicReads:
    def test_list_is_public_paginated_and_hides_inactive(self, api_client, centre):
        DiagnosticCentre.objects.create(
            name="Closed Centre", address="x", city="Pune", pincode="411002", is_active=False
        )

        response = api_client.get(CENTRES_URL)

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"count", "next", "previous", "results"}
        assert [c["name"] for c in body["results"]] == ["Sample Diagnostics Baner"]

    def test_filter_by_city_is_case_insensitive(self, api_client, centre):
        DiagnosticCentre.objects.create(name="M", address="x", city="Mumbai", pincode="400001")

        response = api_client.get(CENTRES_URL, {"city": "pUNE"})

        assert [c["id"] for c in response.json()["results"]] == [str(centre.id)]

    def test_filter_by_test_only_matches_active_offerings(self, api_client, offering):
        other = DiagnosticCentre.objects.create(
            name="Other", address="x", city="Pune", pincode="411003"
        )
        CentreTest.objects.create(
            centre=other, test=offering.test, price=Decimal("10.00"), is_active=False
        )

        response = api_client.get(CENTRES_URL, {"test": str(offering.test_id)})

        assert [c["id"] for c in response.json()["results"]] == [str(offering.centre_id)]

    def test_invalid_filter_value_is_rejected(self, api_client):
        response = api_client.get(CENTRES_URL, {"test": "not-a-uuid"})

        assert response.status_code == 400
        assert "test" in response.json()["error"]["details"]

    def test_search_and_page_size(self, api_client):
        for i in range(3):
            DiagnosticCentre.objects.create(
                name=f"Alpha {i}", address="x", city="Pune", pincode="411001"
            )
        DiagnosticCentre.objects.create(name="Beta", address="x", city="Pune", pincode="411001")

        response = api_client.get(CENTRES_URL, {"search": "alpha", "page_size": 2})

        body = response.json()
        assert body["count"] == 3
        assert len(body["results"]) == 2
        assert body["next"] is not None

    def test_detail_lists_only_active_offerings_with_prices(self, api_client, offering):
        retired = DiagnosticTest.objects.create(code="OLD", name="Retired Test", is_active=False)
        CentreTest.objects.create(centre=offering.centre, test=retired, price=Decimal("1.00"))

        response = api_client.get(centre_url(offering.centre_id))

        assert response.status_code == 200
        tests = response.json()["tests"]
        assert tests == [
            {
                "test": {
                    "id": str(offering.test_id),
                    "code": "CBC",
                    "name": "Complete Blood Count",
                },
                "price": "499.00",
                "currency": "INR",
                "is_active": True,
                "updated_at": tests[0]["updated_at"],
            }
        ]

    def test_detail_query_count_does_not_grow_with_offerings(
        self, api_client, centre, django_assert_max_num_queries
    ):
        for i in range(10):
            test = DiagnosticTest.objects.create(code=f"T{i}", name=f"Test {i}")
            CentreTest.objects.create(centre=centre, test=test, price=Decimal("100.00"))

        with django_assert_max_num_queries(3):
            response = api_client.get(centre_url(centre.id))

        assert len(response.json()["tests"]) == 10

    def test_inactive_centre_is_not_found_for_public(self, api_client, centre):
        centre.is_active = False
        centre.save()

        response = api_client.get(centre_url(centre.id))

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CENTRE_NOT_FOUND"

    def test_unknown_and_malformed_ids_are_404(self, api_client):
        assert api_client.get(centre_url("00000000-0000-0000-0000-000000000000")).status_code == 404
        assert api_client.get(f"{CENTRES_URL}not-a-uuid/").status_code == 404

    def test_offering_list_and_detail(self, api_client, offering):
        listed = api_client.get(offerings_url(offering.centre_id))
        detail = api_client.get(offering_url(offering.centre_id, offering.test_id))

        assert listed.json()["count"] == 1
        assert detail.json()["price"] == "499.00"

    def test_tests_catalog_search_by_code(self, api_client, diagnostic_test):
        DiagnosticTest.objects.create(code="LIPID", name="Lipid Profile")

        response = api_client.get(TESTS_URL, {"search": "cbc"})

        assert [t["code"] for t in response.json()["results"]] == ["CBC"]


class TestWritePermissions:
    @pytest.mark.parametrize("url", [CENTRES_URL, TESTS_URL])
    def test_anonymous_write_is_401(self, api_client, url):
        response = api_client.post(url, CENTRE_PAYLOAD)

        assert response.status_code == 401

    @pytest.mark.parametrize("url", [CENTRES_URL, TESTS_URL])
    def test_patient_write_is_403(self, user_client, url):
        response = user_client.post(url, CENTRE_PAYLOAD)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    def test_patient_cannot_change_price(self, user_client, offering):
        response = user_client.patch(
            offering_url(offering.centre_id, offering.test_id), {"price": "1.00"}
        )

        assert response.status_code == 403
        offering.refresh_from_db()
        assert offering.price == Decimal("499.00")

    def test_put_is_not_allowed(self, admin_client, centre):
        response = admin_client.put(centre_url(centre.id), CENTRE_PAYLOAD)

        assert response.status_code == 405


class TestAdminCentres:
    def test_create_update_and_soft_delete(self, admin_client, api_client):
        created = admin_client.post(CENTRES_URL, CENTRE_PAYLOAD)
        assert created.status_code == 201
        centre_id = created.json()["id"]

        patched = admin_client.patch(centre_url(centre_id), {"name": "Renamed"})
        assert patched.status_code == 200
        assert patched.json()["name"] == "Renamed"

        assert admin_client.delete(centre_url(centre_id)).status_code == 204
        assert DiagnosticCentre.objects.get(id=centre_id).is_active is False
        assert api_client.get(centre_url(centre_id)).status_code == 404
        # Staff can still see and re-enable it.
        assert admin_client.get(centre_url(centre_id)).status_code == 200
        listed = admin_client.get(CENTRES_URL, {"include_inactive": "true"}).json()
        assert centre_id in [c["id"] for c in listed["results"]]

    def test_invalid_pincode(self, admin_client):
        response = admin_client.post(CENTRES_URL, {**CENTRE_PAYLOAD, "pincode": "12"})

        assert response.status_code == 400
        assert "pincode" in response.json()["error"]["details"]

    def test_include_inactive_is_ignored_for_public(self, api_client, centre):
        centre.is_active = False
        centre.save()

        response = api_client.get(CENTRES_URL, {"include_inactive": "true"})

        assert response.json()["count"] == 0


class TestAdminTests:
    def test_code_is_uppercased_and_unique(self, admin_client):
        first = admin_client.post(TESTS_URL, {"code": "hba1c", "name": "HbA1c"})
        assert first.status_code == 201
        assert first.json()["code"] == "HBA1C"

        duplicate = admin_client.post(TESTS_URL, {"code": "HbA1c", "name": "Again"})
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "TEST_CODE_EXISTS"

    def test_rename_code_to_existing_code_conflicts(self, admin_client, diagnostic_test):
        other = DiagnosticTest.objects.create(code="LIPID", name="Lipid Profile")

        response = admin_client.patch(f"{TESTS_URL}{other.id}/", {"code": "cbc"})

        assert response.status_code == 409

    def test_deactivate_test(self, admin_client, api_client, diagnostic_test):
        assert admin_client.delete(f"{TESTS_URL}{diagnostic_test.id}/").status_code == 204
        assert api_client.get(f"{TESTS_URL}{diagnostic_test.id}/").status_code == 404


class TestAdminOfferings:
    def test_add_offering(self, admin_client, centre, diagnostic_test):
        response = admin_client.post(
            offerings_url(centre.id), {"test_id": str(diagnostic_test.id), "price": "250.50"}
        )

        assert response.status_code == 201
        assert response.json()["price"] == "250.50"

    def test_duplicate_offering_conflicts(self, admin_client, offering):
        response = admin_client.post(
            offerings_url(offering.centre_id), {"test_id": str(offering.test_id), "price": "1.00"}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "OFFERING_EXISTS"

    @pytest.mark.parametrize("price", ["0", "-5.00", "10.999", "abc", "123456789.00"])
    def test_invalid_price(self, admin_client, centre, diagnostic_test, price):
        response = admin_client.post(
            offerings_url(centre.id), {"test_id": str(diagnostic_test.id), "price": price}
        )

        assert response.status_code == 400
        assert "price" in response.json()["error"]["details"]

    def test_unknown_test(self, admin_client, centre):
        response = admin_client.post(
            offerings_url(centre.id),
            {"test_id": "00000000-0000-0000-0000-000000000000", "price": "1.00"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "TEST_NOT_FOUND"

    def test_unknown_centre(self, admin_client, diagnostic_test):
        response = admin_client.post(
            offerings_url("00000000-0000-0000-0000-000000000000"),
            {"test_id": str(diagnostic_test.id), "price": "1.00"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CENTRE_NOT_FOUND"

    def test_update_price_and_deactivate(self, admin_client, api_client, offering):
        url = offering_url(offering.centre_id, offering.test_id)

        assert admin_client.patch(url, {"price": "550.00"}).json()["price"] == "550.00"
        assert admin_client.delete(url).status_code == 204
        assert api_client.get(url).status_code == 404
        reenabled = admin_client.patch(url, {"is_active": True})
        assert reenabled.json()["is_active"] is True


class TestDatabaseConstraints:
    def test_price_must_be_positive(self, centre, diagnostic_test):
        with pytest.raises(IntegrityError), transaction.atomic():
            CentreTest.objects.create(centre=centre, test=diagnostic_test, price=Decimal("0"))

    def test_one_price_per_test_per_centre(self, offering):
        with pytest.raises(IntegrityError), transaction.atomic():
            CentreTest.objects.create(
                centre=offering.centre, test=offering.test, price=Decimal("1.00")
            )


def test_seed_catalog_is_idempotent(db):
    call_command("seed_catalog")
    call_command("seed_catalog")

    assert DiagnosticTest.objects.count() == 5
    assert DiagnosticCentre.objects.count() == 3
    assert CentreTest.objects.count() == 11
