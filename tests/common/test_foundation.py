import json
import logging
from unittest import mock

import pytest
from django.db import OperationalError
from rest_framework import exceptions as drf_exceptions

from apps.common.exception_handler import api_exception_handler
from apps.common.exceptions import ConflictError
from apps.common.logging import REDACTED, JsonFormatter, RedactionFilter

pytestmark = pytest.mark.django_db


def test_liveness(api_client):
    response = api_client.get("/health/live/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok(api_client):
    response = api_client.get("/health/ready/")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "ok"


def test_readiness_reports_database_outage(api_client):
    with mock.patch("apps.common.views.connection.cursor", side_effect=OperationalError):
        response = api_client.get("/health/ready/")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_unknown_url_returns_json_error_envelope(api_client):
    response = api_client.get("/definitely/not/here/")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"] == response["X-Request-ID"]


def test_request_id_is_generated_and_echoed(api_client):
    response = api_client.get("/health/live/")
    assert len(response["X-Request-ID"]) == 32


def test_valid_incoming_request_id_is_propagated(api_client):
    response = api_client.get("/health/live/", HTTP_X_REQUEST_ID="trace-abc.123")
    assert response["X-Request-ID"] == "trace-abc.123"


def test_malicious_incoming_request_id_is_replaced(api_client):
    response = api_client.get("/health/live/", HTTP_X_REQUEST_ID="bad id\nwith newline")
    assert response["X-Request-ID"] != "bad id\nwith newline"


def test_openapi_schema_is_served(api_client):
    response = api_client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
    assert response.status_code == 200


class TestExceptionHandler:
    def test_domain_error_maps_to_envelope(self):
        response = api_exception_handler(ConflictError("Nope", code="SOME_CONFLICT"), {})
        assert response.status_code == 409
        assert response.data["error"]["code"] == "SOME_CONFLICT"
        assert response.data["error"]["message"] == "Nope"

    def test_validation_error_puts_fields_in_details(self):
        exc = drf_exceptions.ValidationError({"email": ["Enter a valid email address."]})
        response = api_exception_handler(exc, {})
        assert response.status_code == 400
        assert response.data["error"]["code"] == "VALIDATION_ERROR"
        assert response.data["error"]["details"] == {"email": ["Enter a valid email address."]}

    def test_throttled_sets_retry_after(self):
        response = api_exception_handler(drf_exceptions.Throttled(wait=12.2), {})
        assert response.status_code == 429
        assert response["Retry-After"] == "13"
        assert response.data["error"]["code"] == "RATE_LIMITED"

    def test_unexpected_exception_is_generic_500(self):
        response = api_exception_handler(RuntimeError("secret internals"), {})
        assert response.status_code == 500
        assert response.data["error"]["code"] == "INTERNAL_ERROR"
        assert "secret internals" not in json.dumps(response.data)


def test_log_redaction_and_json_format():
    record = logging.LogRecord("apps.test", logging.INFO, __file__, 1, "event", (), None)
    record.password = "hunter2"
    record.access_token = "abc"
    record.booking_id = "b-1"
    RedactionFilter().filter(record)
    output = json.loads(JsonFormatter().format(record))
    assert output["password"] == REDACTED
    assert output["access_token"] == REDACTED
    assert output["booking_id"] == "b-1"
    assert output["message"] == "event"
