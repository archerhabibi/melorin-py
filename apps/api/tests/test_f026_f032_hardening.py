from melorin.core.storage import validate_upload
from melorin.core.errors import AppError


def test_upload_signatures_reject_empty_and_fake_webp():
    for payload, content_type in ((b"", "image/png"), (b"RIFF" + b"\0" * 20, "image/webp")):
        try:
            validate_upload(payload, content_type)
        except AppError as exc:
            assert exc.code == "INVALID_FILE_SIGNATURE"
        else:
            raise AssertionError("invalid upload accepted")
