from melorin.domain import webhook


def test_webhook_delivery_url_policy_is_https_only_by_default():
    try:
        webhook.check_url("http://example.com/hook")
    except webhook.WebhookUrlError:
        return
    raise AssertionError("plain HTTP webhook accepted")
