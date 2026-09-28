"""Payment provider webhooks: signature verification, the event inbox, and processing.

Idempotency comes from three layers:
  1. One WebhookEvent row per (provider, event_id): duplicate deliveries find the same row.
  2. The event row is locked while processing, so concurrent deliveries run one at a time;
     a delivery that finds the event already PROCESSED/IGNORED returns "duplicate".
  3. apply_payment_result() is itself idempotent and refuses to overwrite a final state.

Events that fail (unknown payment, mismatched data, unexpected error) are stored as FAILED and
processed again when the provider redelivers them or `manage.py retry_webhook_events` runs.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from enum import StrEnum
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.common.exceptions import DomainError
from apps.payments.exceptions import (
    EventIdConflict,
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    PaymentNotFound,
    WebhookPayloadMismatch,
)
from apps.payments.models import Payment, PaymentStatus, WebhookEvent, WebhookEventStatus
from apps.payments.services import ApplyResult, apply_payment_result, lock_booking_and_payment

logger = logging.getLogger(__name__)

PROVIDER = "simulated"
SIGNATURE_HEADER = "X-Webhook-Signature"
TIMESTAMP_HEADER = "X-Webhook-Timestamp"

# Event types we act on, and the payment status each one reports.
HANDLED_EVENT_TYPES = {
    "payment.succeeded": PaymentStatus.SUCCESS,
    "payment.failed": PaymentStatus.FAILED,
}


class WebhookResult(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


# --- Signatures -------------------------------------------------------------------------------


def compute_signature(*, secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over "{timestamp}.{raw body}". Signing the timestamp prevents replays."""
    signed = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def verify_signature(
    *,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret: str,
    tolerance_seconds: int,
    now: float | None = None,
) -> None:
    if not timestamp or not signature or not signature.isascii():
        raise InvalidWebhookSignature()
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise InvalidWebhookSignature() from exc
    current = time.time() if now is None else now
    if abs(current - sent_at) > tolerance_seconds:
        raise InvalidWebhookSignature("Webhook timestamp is outside the allowed window.")
    expected = compute_signature(secret=secret, timestamp=timestamp, body=body)
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        raise InvalidWebhookSignature()


# --- Payload ----------------------------------------------------------------------------------


class WebhookEnvelopeSerializer(serializers.Serializer):
    event_id = serializers.RegexField(r"^[\x21-\x7e]{1,128}$")
    event_type = serializers.CharField(max_length=64)
    occurred_at = serializers.DateTimeField()
    data = serializers.DictField()


class PaymentEventDataSerializer(serializers.Serializer):
    payment_reference = serializers.CharField(max_length=64)
    booking_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    failure_reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )


def parse_payload(body: bytes) -> dict[str, Any]:
    """Decode and validate the JSON body. Payment events must also carry valid payment data."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidWebhookPayload("Webhook body is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise InvalidWebhookPayload("Webhook body must be a JSON object.")

    envelope = WebhookEnvelopeSerializer(data=payload)
    if not envelope.is_valid():
        raise InvalidWebhookPayload(details=envelope.errors)
    if payload["event_type"] in HANDLED_EVENT_TYPES:
        data = PaymentEventDataSerializer(data=payload["data"])
        if not data.is_valid():
            raise InvalidWebhookPayload(details={"data": data.errors})
    return payload


def payload_hash(payload: dict[str, Any]) -> str:
    """Hash of the canonical JSON, so key order and whitespace don't count as "different"."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# --- Inbox ------------------------------------------------------------------------------------


def receive_event(payload: dict[str, Any], *, provider: str = PROVIDER) -> WebhookEvent:
    """Store the event once. A redelivery returns the existing row."""
    digest = payload_hash(payload)
    # get_or_create resolves concurrent inserts via the unique constraint.
    event, created = WebhookEvent.objects.get_or_create(
        provider=provider,
        event_id=payload["event_id"],
        defaults={
            "event_type": payload["event_type"],
            "payload": payload,
            "payload_hash": digest,
        },
    )
    log_extra = {"webhook_event_id": event.event_id, "event_type": event.event_type}
    if not created and event.payload_hash != digest:
        logger.warning("webhook.event_id_conflict", extra=log_extra)
        raise EventIdConflict()
    logger.info("webhook.received" if created else "webhook.redelivered", extra=log_extra)
    return event


def process_event(event_pk: uuid.UUID) -> WebhookResult:
    """Apply a stored event. Safe to call any number of times, concurrently or not."""
    try:
        with transaction.atomic():
            event = WebhookEvent.objects.select_for_update().get(pk=event_pk)
            if event.status in (WebhookEventStatus.PROCESSED, WebhookEventStatus.IGNORED):
                logger.info("webhook.duplicate", extra={"webhook_event_id": event.event_id})
                return WebhookResult.DUPLICATE
            event.attempts += 1
            result, note = _apply_event(event)
            event.status = (
                WebhookEventStatus.PROCESSED
                if result == WebhookResult.PROCESSED
                else WebhookEventStatus.IGNORED
            )
            event.last_error = note
            event.processed_at = timezone.now()
            event.save()
            return result
    except DomainError as exc:
        _mark_failed(event_pk, f"{exc.code}: {exc.message}")
        raise
    except Exception as exc:
        _mark_failed(event_pk, f"{type(exc).__name__}: {exc}")
        raise


def _apply_event(event: WebhookEvent) -> tuple[WebhookResult, str]:
    target_status = HANDLED_EVENT_TYPES.get(event.event_type)
    if target_status is None:
        logger.info(
            "webhook.ignored_event_type",
            extra={"webhook_event_id": event.event_id, "event_type": event.event_type},
        )
        return WebhookResult.IGNORED, "Unhandled event type."

    data = PaymentEventDataSerializer(data=event.payload["data"])
    data.is_valid(raise_exception=True)
    values = data.validated_data

    try:
        payment_pk = Payment.objects.values_list("pk", flat=True).get(
            provider=event.provider, provider_reference=values["payment_reference"]
        )
    except Payment.DoesNotExist as exc:
        raise PaymentNotFound("No payment matches this payment_reference.") from exc

    booking, payment = lock_booking_and_payment(payment_pk)
    mismatched = sorted(
        field
        for field, matches in {
            "booking_id": payment.booking_id == values["booking_id"],
            "amount": payment.amount == values["amount"],
            "currency": payment.currency == values["currency"],
        }.items()
        if not matches
    )
    if mismatched:
        logger.warning(
            "webhook.payload_mismatch",
            extra={"webhook_event_id": event.event_id, "payment_id": str(payment.pk)},
        )
        raise WebhookPayloadMismatch(details={"fields": mismatched})

    event.payment = payment
    outcome = apply_payment_result(
        booking=booking,
        payment=payment,
        status=target_status,
        failure_reason=values.get("failure_reason") or "",
        source="webhook",
    )
    if outcome == ApplyResult.CONFLICT:
        return WebhookResult.IGNORED, (
            f"Conflicting result: payment is already {payment.status}, event reports "
            f"{target_status}. Needs reconciliation with the provider."
        )
    return WebhookResult.PROCESSED, ""


def _mark_failed(event_pk: uuid.UUID, error: str) -> None:
    with transaction.atomic():
        event = WebhookEvent.objects.select_for_update().get(pk=event_pk)
        if event.status in (WebhookEventStatus.PROCESSED, WebhookEventStatus.IGNORED):
            return  # a concurrent delivery succeeded in the meantime
        event.status = WebhookEventStatus.FAILED
        event.attempts += 1
        event.last_error = error[:2000]
        event.save(update_fields=["status", "attempts", "last_error", "updated_at"])
    logger.warning(
        "webhook.failed",
        extra={"webhook_event_id": event.event_id, "attempts": event.attempts},
    )
