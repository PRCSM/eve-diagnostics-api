import pytest

from apps.payments.exceptions import InvalidWebhookSignature
from apps.payments.webhooks import compute_signature, verify_signature

SECRET = "unit-test-secret"
BODY = b'{"event_id":"evt_1"}'
NOW = 1_800_000_000


def verify(**overrides):
    params = {
        "body": BODY,
        "timestamp": str(NOW),
        "signature": compute_signature(secret=SECRET, timestamp=str(NOW), body=BODY),
        "secret": SECRET,
        "tolerance_seconds": 300,
        "now": NOW,
    }
    params.update(overrides)
    verify_signature(**params)


def test_valid_signature_passes():
    verify()


def test_signature_format():
    assert compute_signature(secret=SECRET, timestamp="1", body=b"x").startswith("sha256=")


@pytest.mark.parametrize(
    "overrides",
    [
        {"signature": None},
        {"timestamp": None},
        {"timestamp": "not-a-number"},
        {"signature": "sha256=" + "0" * 64},
        {"signature": "sha256=é"},
        {"body": BODY + b" "},
        {"secret": "another-secret"},
        {"now": NOW + 301},
        {"now": NOW - 301},
    ],
    ids=[
        "missing-signature",
        "missing-timestamp",
        "bad-timestamp",
        "wrong-signature",
        "non-ascii",
        "tampered-body",
        "wrong-secret",
        "stale",
        "from-the-future",
    ],
)
def test_invalid_signatures_are_rejected(overrides):
    with pytest.raises(InvalidWebhookSignature):
        verify(**overrides)


def test_timestamp_is_part_of_the_signed_material():
    old = compute_signature(secret=SECRET, timestamp=str(NOW - 1000), body=BODY)

    with pytest.raises(InvalidWebhookSignature):
        verify(signature=old)
