"""T13: the vision (Messages API) request is built in exactly one place."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "melorin"


def test_only_receipt_ocr_talks_to_the_messages_api():
    hits = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py") if "/v1/messages" in p.read_text(encoding="utf-8"))
    assert hits == ["modules/payments/receipt_ocr.py"]
