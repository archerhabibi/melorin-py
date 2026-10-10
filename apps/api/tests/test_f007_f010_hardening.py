from melorin.core.storage import validate_upload
from melorin.core.errors import AppError
from melorin.domain import webhook


def test_webp_requires_webp_container_marker():
    try:
        validate_upload(b"RIFF" + b"\x00" * 20, "image/webp")
    except AppError as exc:
        assert exc.code == "INVALID_FILE_SIGNATURE"
    else:
        raise AssertionError("invalid WebP accepted")


def test_backup_relevant_webhook_signature_is_exact():
    body = webhook.canonical_body({"id": "evt-1"})
    header = webhook.sign("secret", 100, body)
    assert webhook.verify("secret", header, body, now=100)
    assert not webhook.verify("wrong", header, body, now=100)
