"""Receipt facts are read from the image automatically (OCR / vision); the customer types nothing.

The deposit SMS stays the only proof: a reading can narrow candidates and block a mismatching amount, never pay by itself.
"""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from _http import api_client
from melorin.domain import bank_sms as dom
from melorin.domain.receipt_text import ReceiptFacts, facts_from_mapping, parse_receipt_text
from melorin.modules.payments import bank_sms, receipt_ocr
from test_bank_sms_auto_verify import PNG, SERIAL, _balance, _login, _minute, _setup_source, _sms, sms_text  # noqa: F401

# What a text OCR returns for the receipt in the owner's example (digits/labels in the order engines emit them).
RECEIPT_TEXT = """
رحیم حبیبی
8493 7473 7311 6063
1,500,000 ریال
مبلغ انتقال
انتقال موفق
زمان ۲۲:۵۰ شنبه، ۲ آبان ۱۴۰۵
انتقال دهنده محمدطاها میرزائی تنها
روش انتقال کارت به کارت
کارت مبدا ۶۲۱۹ ۸۶** **** ۷۹۳۱
شماره مرجع ۲۸۶۹۶۱۱۲۲۷۶۲
"""


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    from melorin.core import storage

    monkeypatch.setattr(storage, "_storage", storage.LocalStorage(str(tmp_path)))


# ------------------------------------------------------------------------------------------------ pure parser
def test_parser_reads_the_example_receipt():
    f = parse_receipt_text(RECEIPT_TEXT)
    assert f.amount_rial == 1_500_000
    assert dom.utc_to_jalali_text(f.paid_at) == "1405/08/02 22:50"
    assert f.paid_at == dt.datetime(2026, 10, 24, 19, 20, tzinfo=dt.UTC)
    assert f.source_last4 == "7931"
    assert f.reference == "28696112276" + "2"


def test_parser_handles_visual_order_toman_and_numeric_dates():
    visual = RECEIPT_TEXT.replace("۶۲۱۹ ۸۶** **** ۷۹۳۱", "۷۹۳۱ **** **۸۶ ۶۲۱۹")
    assert parse_receipt_text(visual).source_last4 == "7931"
    f = parse_receipt_text("مبلغ 150,000 تومان\nتاریخ 1405/08/02 ساعت 22:50\nشماره پیگیری 123456789")
    assert f.amount_rial == 1_500_000 and dom.utc_to_jalali_text(f.paid_at) == "1405/08/02 22:50" and f.reference == "123456789"


def test_parser_never_guesses():
    assert parse_receipt_text("").found is False
    assert parse_receipt_text("زمان 22:50").paid_at is None  # clock time without a date is not a timestamp
    assert parse_receipt_text("کارت مبدا ۶۲۱۹ ۸۶** **** ۷۹").source_last4 is None
    assert parse_receipt_text("زمان 25:61 ۲ آبان ۱۴۰۵").paid_at is None
    # a fully printed card: only the order that passes Luhn is accepted
    assert parse_receipt_text("کارت مبدا 4111 1111 1111 1111").source_last4 == "1111"
    assert parse_receipt_text("کارت مبدا 1234 5678 9012 3456").source_last4 is None


def test_vision_answer_is_revalidated():
    f = facts_from_mapping(
        {"amount_rial": "۱٬۵۰۰٬۰۰۰", "paid_at": "1405/08/02 22:50", "source_card_last4": "7931", "reference": "2869611227 62"}
    )
    assert f == ReceiptFacts(1_500_000, dt.datetime(2026, 10, 24, 19, 20, tzinfo=dt.UTC), "7931", "286961122762")
    bad = facts_from_mapping({"amount_rial": -5, "paid_at": "yesterday", "source_card_last4": "12", "reference": "1"})
    assert bad.found is False
    assert facts_from_mapping({"amount_toman": 150000}).amount_rial == 1_500_000


# ------------------------------------------------------------------------------------------------ engines
async def test_vision_engine_calls_the_provider_with_the_image_and_parses_json(monkeypatch):
    from melorin.core import config

    monkeypatch.setenv("MELORIN_RECEIPT_OCR_ENGINE", "vision")
    monkeypatch.setenv("MELORIN_RECEIPT_OCR_API_KEY", "k-test")
    config.get_settings.cache_clear()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"] = str(request.url), request.headers["x-api-key"]
        seen["body"] = json.loads(request.content)
        answer = '```json\n{"amount_rial": 1500000, "paid_at": "1405/08/02 22:50", "source_card_last4": "7931", "reference": "286961122762"}\n```'
        return httpx.Response(200, json={"content": [{"type": "text", "text": answer}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(receipt_ocr.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    facts, engine = await receipt_ocr.read_receipt(PNG, "image/png")
    assert engine == "vision" and facts.amount_rial == 1_500_000 and facts.source_last4 == "7931"
    assert seen["url"].endswith("/v1/messages") and seen["key"] == "k-test"
    content = seen["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    assert "untrusted" in seen["body"]["system"]
    config.get_settings.cache_clear()


async def test_engine_failure_never_raises_and_pdf_is_skipped(monkeypatch):
    from melorin.core import config

    monkeypatch.setenv("MELORIN_RECEIPT_OCR_ENGINE", "vision")
    monkeypatch.setenv("MELORIN_RECEIPT_OCR_API_KEY", "k-test")
    config.get_settings.cache_clear()
    real = httpx.AsyncClient
    monkeypatch.setattr(
        receipt_ocr.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw)
    )
    assert await receipt_ocr.read_receipt(PNG, "image/png") == (None, "vision")
    assert await receipt_ocr.read_receipt(b"%PDF-1.4", "application/pdf") == (None, None)
    monkeypatch.setenv("MELORIN_RECEIPT_OCR_ENGINE", "off")
    config.get_settings.cache_clear()
    assert await receipt_ocr.read_receipt(PNG, "image/png") == (None, None)
    config.get_settings.cache_clear()


# ------------------------------------------------------------------------------------------------ end to end
def _engine(monkeypatch, facts, name="vision"):
    async def fake(data, content_type):
        return facts, name

    monkeypatch.setattr(receipt_ocr, "read_receipt", fake)


async def _topup_plain(c, h, sid, *, amount=150_000, key="manual-key-1"):
    r = await c.post(
        f"/api/v1/stores/{sid}/wallet/topups", json={"amount": amount, "provider": "manual_card"}, headers={**h, "Idempotency-Key": key}
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _upload(c, h, sid, pid, **form):
    return await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": ("r.png", PNG, "image/png")}, data=form, headers=h)


async def test_customer_types_nothing_and_the_wallet_is_still_credited(monkeypatch):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        _engine(monkeypatch, ReceiptFacts(1_500_000, when, "7931", "286961122762"))
        pid = await _topup_plain(c, h, sid)
        r = await _upload(c, h, sid, pid)  # no paid_at, no card digits, no reference
        assert r.status_code == 200
        assert r.json()["receipt_read"]["source"] == "ocr" and r.json()["receipt_read"]["source_card_last4"] == "7931"
        assert (await _sms(c, main.id, token, sms_text(when=when))).json()["status"] == "matched"
        assert await _balance(maker, sid) == 150_000


async def test_receipt_amount_that_disagrees_with_the_request_is_never_auto_paid(monkeypatch):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        _engine(monkeypatch, ReceiptFacts(999_000, when, "7931", None))  # image says 99,900 toman, request is 150,000
        pid = await _topup_plain(c, h, sid)
        await _upload(c, h, sid, pid)
        assert (await _sms(c, main.id, token, sms_text(when=when))).json()["status"] == "unmatched"
        assert await _balance(maker, sid) == 0


async def test_unreadable_receipt_waits_for_a_human_and_typed_time_is_only_a_fallback(monkeypatch):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        _engine(monkeypatch, None, "tesseract")  # OCR could not read anything
        pid = await _topup_plain(c, h, sid)
        r = await _upload(c, h, sid, pid)
        assert r.status_code == 200 and r.json()["status"] == "awaiting_review" and r.json()["receipt_read"]["source"] == "none"
        assert (await _sms(c, main.id, token, sms_text(when=when))).json()["status"] == "unmatched"
        r = await _upload(c, h, sid, pid, paid_at=dom.utc_to_jalali_text(when))  # fallback form, same receipt again
        assert r.json()["status"] == "succeeded" and r.json()["receipt_read"]["source"] == "customer"
        assert await _balance(maker, sid) == 150_000


async def test_same_amount_same_minute_deposits_are_two_sms_not_one_duplicate():
    """The first SMS line is the ACCOUNT number (identical for every deposit): the balance tells deposits apart."""
    async with api_client() as (c, maker, main):
        _, _ = await _login(c, maker)
        token = await _setup_source(maker, main.id)
        when = _minute()
        a = (await _sms(c, main.id, token, sms_text(when=when, balance=107_923_032))).json()
        b = (await _sms(c, main.id, token, sms_text(when=when, balance=109_423_032))).json()
        again = (await _sms(c, main.id, token, sms_text(when=when, balance=109_423_032))).json()
        assert (a["duplicate"], b["duplicate"], again["duplicate"]) == (False, False, True)


async def test_sms_of_another_account_is_ignored_when_the_account_is_pinned(monkeypatch):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        token = await _setup_source(maker, main.id, settings={"account_number": SERIAL})
        when = _minute()
        _engine(monkeypatch, ReceiptFacts(1_500_000, when, None, None))
        pid = await _topup_plain(c, h, sid)
        await _upload(c, h, sid, pid)
        other = sms_text(when=when, serial="999999999999999999")
        assert (await _sms(c, main.id, token, other)).json()["status"] == "ignored"
        assert await _balance(maker, sid) == 0
        assert (await _sms(c, main.id, token, sms_text(when=when))).json()["status"] == "matched"


def test_account_number_setting_is_validated():
    assert bank_sms.clean_settings({"account_number": "۳۰۲۵۷۰۰۰۹۱۵۲۳۲۵۰۰۱"}) == {"account_number": SERIAL}
    with pytest.raises(Exception):
        bank_sms.clean_settings({"account_number": "12"})
