from melorin.domain import webhook


def test_webhook_signature_has_timestamp_and_is_replay_bounded():
    body = webhook.canonical_body({"event": "order.completed"})
    now = 1_700_000_000
    header = webhook.sign("secret", now, body)
    assert webhook.verify("secret", header, body, now=now)
    assert not webhook.verify("secret", header, body, now=now + webhook.DEFAULT_TOLERANCE + 1)


def test_webhook_backoff_is_bounded():
    assert webhook.next_delay(1) == 30
    assert webhook.next_delay(webhook.MAX_ATTEMPTS) is None


def test_webhook_rejects_private_and_non_https_targets():
    for url in (
        "http://example.com/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.8/hook",
        "https://192.168.1.8/hook",
        "https://[::1]/hook",
        "https://localhost/hook",
    ):
        try:
            webhook.check_url(url)
        except webhook.WebhookUrlError:
            pass
        else:
            raise AssertionError(url)


def test_webhook_rejects_private_resolved_addresses():
    for address in ("127.0.0.1", "10.0.0.8", "::1", "fc00::1"):
        try:
            webhook.check_url("https://example.com/hook", resolved_ips=[address])
        except webhook.WebhookUrlError:
            pass
        else:
            raise AssertionError(address)
