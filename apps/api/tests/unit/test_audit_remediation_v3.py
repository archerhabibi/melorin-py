"""Regression tests for the third audit pass (V-021 OCR endpoint policy, V-21 OCR budget, V-11 nonce cookie)."""

import pytest

from melorin.core.config import get_settings
from melorin.modules.payments import receipt_ocr


@pytest.mark.parametrize(
    "url",
    [
        "https://100.100.100.200",  # CGNAT / Alibaba metadata
        "https://127.1",  # legacy numeric loopback
        "https://2130706433",  # decimal loopback
        "https://localhost",
        "https://metadata.internal",
        "http://api.anthropic.com",  # not https
        "https://user:pw@api.anthropic.com",  # credentials in URL
    ],
)
async def test_ocr_endpoint_refuses_unsafe_urls(url):
    with pytest.raises(receipt_ocr.OcrEndpointForbidden):
        await receipt_ocr.assert_public_endpoint(url)


async def test_ocr_endpoint_refuses_name_resolving_to_private(monkeypatch):
    import asyncio

    async def fake(self, host, port, **kw):
        return [(2, 1, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(asyncio.get_running_loop().__class__, "getaddrinfo", fake)
    with pytest.raises(receipt_ocr.OcrEndpointForbidden):
        await receipt_ocr.assert_public_endpoint("https://rebind.example.com")


async def test_ocr_endpoint_accepts_public(monkeypatch):
    import asyncio

    async def fake(self, host, port, **kw):
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(asyncio.get_running_loop().__class__, "getaddrinfo", fake)
    await receipt_ocr.assert_public_endpoint("https://api.anthropic.com")


def test_ocr_daily_cap_has_a_sane_default():
    assert 0 < get_settings().receipt_ocr_daily_cap <= 10_000
