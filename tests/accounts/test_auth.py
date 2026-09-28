import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from tests.conftest import DEFAULT_PASSWORD

pytestmark = pytest.mark.django_db

SIGNUP_URL = "/api/v1/auth/signup/"
LOGIN_URL = "/api/v1/auth/login/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"


def signup_payload(**overrides) -> dict:
    payload = {
        "email": "new.patient@example.com",
        "password": "a-long-passphrase-42",
        "full_name": "New Patient",
        "phone": "+910000000000",
    }
    payload.update(overrides)
    return payload


def login(api_client, email: str, password: str = DEFAULT_PASSWORD):
    return api_client.post(LOGIN_URL, {"email": email, "password": password})


class TestSignup:
    def test_creates_regular_user_with_hashed_password(self, api_client):
        response = api_client.post(SIGNUP_URL, signup_payload(email="New.Patient@Example.COM"))

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "new.patient@example.com"
        assert body["is_staff"] is False
        assert "password" not in body
        user = User.objects.get(id=body["id"])
        assert user.password != "a-long-passphrase-42"
        assert user.check_password("a-long-passphrase-42")

    def test_privileged_fields_are_ignored(self, api_client):
        payload = signup_payload(is_staff=True, is_superuser=True)
        response = api_client.post(SIGNUP_URL, payload)

        assert response.status_code == 201
        user = User.objects.get(id=response.json()["id"])
        assert not user.is_staff
        assert not user.is_superuser

    def test_duplicate_email_is_case_insensitive(self, api_client, user):
        response = api_client.post(SIGNUP_URL, signup_payload(email="PATIENT@example.com"))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"

    def test_weak_password_is_rejected(self, api_client):
        response = api_client.post(SIGNUP_URL, signup_payload(password="12345678"))

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "password" in error["details"]

    @pytest.mark.parametrize(
        "overrides, field",
        [
            ({"email": "not-an-email"}, "email"),
            ({"full_name": ""}, "full_name"),
            ({"phone": "call me"}, "phone"),
        ],
    )
    def test_invalid_fields(self, api_client, overrides, field):
        response = api_client.post(SIGNUP_URL, signup_payload(**overrides))

        assert response.status_code == 400
        assert field in response.json()["error"]["details"]

    def test_missing_body(self, api_client):
        response = api_client.post(SIGNUP_URL, {})

        assert response.status_code == 400
        assert set(response.json()["error"]["details"]) >= {"email", "password", "full_name"}

    def test_malformed_json(self, api_client):
        response = api_client.post(SIGNUP_URL, "{not json", content_type="application/json")

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_signup_ignores_bad_authorization_header(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer garbage")
        response = api_client.post(SIGNUP_URL, signup_payload())

        assert response.status_code == 201


class TestLogin:
    def test_returns_token_pair_that_authenticates(self, api_client, user):
        response = login(api_client, "patient@example.com")

        assert response.status_code == 200
        body = response.json()
        assert body["user"]["id"] == str(user.id)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        me = api_client.get(ME_URL)
        assert me.status_code == 200
        assert me.json()["email"] == "patient@example.com"

    def test_email_is_case_insensitive(self, api_client, user):
        assert login(api_client, "Patient@Example.com").status_code == 200

    @pytest.mark.parametrize(
        "email, password",
        [("patient@example.com", "wrong-password"), ("nobody@example.com", DEFAULT_PASSWORD)],
    )
    def test_bad_credentials_share_one_generic_error(self, api_client, user, email, password):
        response = login(api_client, email, password)

        assert response.status_code == 401
        error = response.json()["error"]
        assert error["code"] == "INVALID_CREDENTIALS"
        assert error["message"] == "Invalid email or password."

    def test_inactive_user_cannot_log_in(self, api_client, make_user):
        make_user(email="inactive@example.com", is_active=False)

        response = login(api_client, "inactive@example.com")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_login_is_rate_limited(self, api_client, user):
        for _ in range(10):
            login(api_client, "patient@example.com", "wrong-password")

        response = login(api_client, "patient@example.com", "wrong-password")

        assert response.status_code == 429
        assert response.json()["error"]["code"] == "RATE_LIMITED"
        assert int(response["Retry-After"]) > 0


class TestTokens:
    def test_me_requires_authentication(self, api_client):
        response = api_client.get(ME_URL)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"
        assert response["WWW-Authenticate"].startswith("Bearer")

    def test_garbage_token_is_rejected(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-jwt")

        response = api_client.get(ME_URL)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_INVALID"

    def test_deactivated_user_token_stops_working(self, user_client, user):
        user.is_active = False
        user.save()

        assert user_client.get(ME_URL).status_code == 401

    def test_refresh_rotates_and_old_token_is_blacklisted(self, api_client, user):
        first = login(api_client, "patient@example.com").json()

        rotated = api_client.post(REFRESH_URL, {"refresh": first["refresh"]})
        assert rotated.status_code == 200
        assert rotated.json()["refresh"] != first["refresh"]

        reused = api_client.post(REFRESH_URL, {"refresh": first["refresh"]})
        assert reused.status_code == 401
        assert reused.json()["error"]["code"] == "TOKEN_INVALID"

    def test_logout_blacklists_refresh_token(self, api_client, user):
        tokens = login(api_client, "patient@example.com").json()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        response = api_client.post(LOGOUT_URL, {"refresh": tokens["refresh"]})
        assert response.status_code == 204

        api_client.credentials()
        after = api_client.post(REFRESH_URL, {"refresh": tokens["refresh"]})
        assert after.status_code == 401

    def test_cannot_log_out_someone_elses_token(self, api_client, user, other_client):
        tokens = login(api_client, "patient@example.com").json()

        response = other_client.post(LOGOUT_URL, {"refresh": tokens["refresh"]})

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "TOKEN_INVALID"

    def test_logout_with_invalid_token(self, user_client):
        response = user_client.post(LOGOUT_URL, {"refresh": "garbage"})

        assert response.status_code == 401


class TestUserModelConstraints:
    def test_database_rejects_mixed_case_email(self, user):
        # .update() bypasses model.save() normalisation; the CHECK constraint still holds.
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=user.pk).update(email="Patient@Example.com")

    def test_superuser_is_staff(self, db):
        admin = User.objects.create_superuser(
            email="Root@Example.com", password=DEFAULT_PASSWORD, full_name="Admin"
        )
        assert admin.is_staff and admin.is_superuser
        assert admin.email == "root@example.com"
