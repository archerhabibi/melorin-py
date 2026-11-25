"""OCR providers must not keep a worker busy or buffer unbounded responses."""

import asyncio
import gzip
import time

import httpx
import pytest

from melorin.modules.payments import receipt_ocr


def _provider(monkeypatch, stream, headers=None):
    async def resolve(_url):
        return "8.8.8.8"

    async def handle(_request):
        return httpx.Response(200, headers=headers, stream=stream)

    monkeypatch.setattr(receipt_ocr, "assert_public_endpoint", resolve)
    monkeypatch.setattr(
        receipt_ocr,
        "outbound_client",
        lambda _purpose, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False, **kw),
    )


def _config():
    return receipt_ocr.OcrConfig("vision", "test-key", "https://ocr.example", "test-model", 1, "eng")


async def test_oversized_provider_response_stops_before_reading_the_whole_body(monkeypatch):
    class Flood(httpx.AsyncByteStream):
        reads = 0

        async def __aiter__(self):
            for _ in range(64):
                self.reads += 1
                yield b"x" * 65536

    stream = Flood()
    _provider(monkeypatch, stream)
    with pytest.raises(ValueError, match="response.*too large"):
        await receipt_ocr.post_vision(_config(), b"image", "image/png", "read", max_tokens=3)
    assert stream.reads < 64


async def test_provider_that_drips_data_cannot_exceed_the_total_deadline(monkeypatch):
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.05)
                yield b"x"

    _provider(monkeypatch, SlowStream())
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(3):
            await receipt_ocr.post_vision(_config(), b"image", "image/png", "read", max_tokens=3)
    assert time.monotonic() - started < 2


async def test_compressed_provider_response_is_not_decompressed_without_a_limit(monkeypatch):
    class Compressed(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield gzip.compress(b"small response")

    _provider(monkeypatch, Compressed(), {"Content-Encoding": "gzip"})
    with pytest.raises(ValueError, match="compressed"):
        await receipt_ocr.post_vision(_config(), b"image", "image/png", "read", max_tokens=3)
