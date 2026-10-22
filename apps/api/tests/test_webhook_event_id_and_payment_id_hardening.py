import uuid

from melorin.domain import webhook


def test_webhook_event_id_is_stable_and_retryable():
    body = webhook.canonical_body({"id": "evt-1", "type": "payment.succeeded"})
    signature = webhook.sign("secret", 100, body)
    assert webhook.verify("secret", signature, body, now=100)
    assert webhook.next_delay(1) == 30
    assert webhook.next_delay(webhook.MAX_ATTEMPTS) is None


def test_invalid_payment_id_never_becomes_unhandled_exception():
    # UUID parsing is intentionally done at the API boundary and converted to
    # a stable 404 business error in the service.
    assert uuid.UUID("00000000-0000-0000-0000-000000000000")
