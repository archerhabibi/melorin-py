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
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
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
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw))
    assert await receipt_ocr.read_receipt(PNG, "image/png") == (None, "vision")
    assert await receipt_ocr.read_receipt(b"%PDF-1.4", "application/pdf") == (None, None)
    monkeypatch.setenv("MELORIN_RECEIPT_OCR_ENGINE", "off")
    config.get_settings.cache_clear()
    assert await receipt_ocr.read_receipt(PNG, "image/png") == (None, None)
    config.get_settings.cache_clear()


# ------------------------------------------------------------------------------------------------ end to end
def _engine(monkeypatch, facts, name="vision"):
    """A configured engine (the upload only queues a reading when one is set) whose result is ``facts``."""
    from melorin.core import config

    monkeypatch.setenv("MELORIN_RECEIPT_OCR_ENGINE", "vision")
    monkeypatch.setenv("MELORIN_RECEIPT_OCR_API_KEY", "k-test")
    config.get_settings.cache_clear()

    async def fake(data, content_type, cfg=None):
        return facts, name

    monkeypatch.setattr(receipt_ocr, "read_receipt", fake)


async def _drain_ocr(maker) -> list[str]:
    """Run the queued receipt readings the way the worker does (V01 V-21: the upload never reads the picture itself)."""
    from sqlalchemy import select

    from melorin.core import events
    from melorin.kernel.models.system import OutboxEvent
    from melorin.modules.payments import ocr_job

    async with maker() as s:
        payloads = [e.payload for e in (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == events.RECEIPT_OCR))).all()]
    results = []
    for payload in payloads:
        async with maker() as s:
            results.append(await ocr_job.run(s, payload))
    return results


async def _payment(c, h, sid, pid):
    r = await c.get(f"/api/v1/stores/{sid}/payments/{pid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


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
        assert (
            r.json()["receipt_read"]["ocr_state"] == "pending" and r.json()["receipt_read"]["source"] == "none"
        )  # answered before reading
        assert await _drain_ocr(maker) == ["done"]
        read = (await _payment(c, h, sid, pid))["receipt_read"]
        assert read["source"] == "ocr" and read["source_card_last4"] == "7931" and read["ocr_state"] == "done"
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
        await _drain_ocr(maker)
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
        assert r.status_code == 200 and r.json()["status"] == "awaiting_review"
        await _drain_ocr(maker)
        assert (await _payment(c, h, sid, pid))["receipt_read"]["source"] == "none"
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
        await _drain_ocr(maker)
        other = sms_text(when=when, serial="999999999999999999")
        assert (await _sms(c, main.id, token, other)).json()["status"] == "ignored"
        assert await _balance(maker, sid) == 0
        assert (await _sms(c, main.id, token, sms_text(when=when))).json()["status"] == "matched"


def test_account_number_setting_is_validated():
    assert bank_sms.clean_settings({"account_number": "۳۰۲۵۷۰۰۰۹۱۵۲۳۲۵۰۰۱"}) == {"account_number": SERIAL}
    with pytest.raises(Exception):
        bank_sms.clean_settings({"account_number": "12"})


# ------------------------------------------------------------------------------------------------ V01 V-21: reading is a worker job
async def test_upload_never_reads_the_picture_itself(monkeypatch):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id)
        calls = []

        async def fake(data, content_type, cfg=None):
            calls.append(len(data))
            return ReceiptFacts(1_500_000, _minute(), "7931", "286961122762"), "vision"

        _engine(monkeypatch, None)
        monkeypatch.setattr(receipt_ocr, "read_receipt", fake)
        pid = await _topup_plain(c, h, sid)
        r = await _upload(c, h, sid, pid)
        assert r.status_code == 200 and calls == []  # the request returned without touching the engine
        assert await _drain_ocr(maker) == ["done"] and len(calls) == 1
        assert await _drain_ocr(maker) == ["stale"] and len(calls) == 1  # a re-delivered event does no second (paid) reading


async def test_replacing_the_receipt_discards_the_older_reading(monkeypatch):
    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id)
        _engine(monkeypatch, ReceiptFacts(1_500_000, _minute(), "7931", None))
        pid = await _topup_plain(c, h, sid)
        await _upload(c, h, sid, pid)
        first = await _drain_ocr(maker)
        assert first == ["done"]
        # same picture again: its fingerprint warns but the upload is accepted; the new file id gets its own queued reading
        await c.post(f"/api/v1/stores/{sid}/payments/{pid}/receipt", files={"file": ("r2.png", PNG + b"\x00", "image/png")}, headers=h)
        results = await _drain_ocr(maker)
        assert results.count("stale") == 1 and results.count("done") == 1  # the old event is stale, only the new file was read once more


async def test_daily_vision_budget_is_spent_in_the_worker_and_the_receipt_stays_with_a_human(monkeypatch):
    from melorin.core import config

    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id)
        monkeypatch.setenv("MELORIN_RECEIPT_OCR_DAILY_CAP", "1")
        _engine(monkeypatch, ReceiptFacts(1_500_000, _minute(), "7931", None))
        config.get_settings.cache_clear()
        a = await _topup_plain(c, h, sid, key="manual-key-a1")
        b = await _topup_plain(c, h, sid, key="manual-key-b1")
        for pid in (a, b):
            assert (await _upload(c, h, sid, pid)).status_code == 200
        assert sorted(await _drain_ocr(maker)) == ["done", "skipped"]
        reads = [(await _payment(c, h, sid, pid))["receipt_read"] for pid in (a, b)]
        assert sorted(x["source"] for x in reads) == ["none", "ocr"]
        assert all(x["ocr_state"] in ("done", "skipped") for x in reads)
    config.get_settings.cache_clear()


async def test_engine_off_queues_nothing(monkeypatch):
    from melorin.core import config

    async with api_client() as (c, maker, main):
        h, sid = await _login(c, maker)
        await _setup_source(maker, main.id)
        monkeypatch.setenv("MELORIN_RECEIPT_OCR_ENGINE", "off")
        config.get_settings.cache_clear()
        pid = await _topup_plain(c, h, sid)
        r = await _upload(c, h, sid, pid)
        assert r.status_code == 200 and r.json()["receipt_read"]["ocr_state"] is None
        assert await _drain_ocr(maker) == []
    config.get_settings.cache_clear()


async def test_grace_credit_waits_for_a_pending_reading():
    from types import SimpleNamespace

    from melorin.core.db import utcnow
    from melorin.modules.payments import ocr_job, provisional

    def pay(state, minutes_ago):
        queued = (utcnow() - dt.timedelta(minutes=minutes_ago)).isoformat()
        return SimpleNamespace(
            amount=150_000,
            currency="IRT",
            meta={"receipt_ocr": {"state": state, "queued_at": queued}, "receipt_claim": {"reference": "123456789"}},
        )

    assert ocr_job.blocks_credit(pay("pending", 2)) is True
    assert ocr_job.blocks_credit(pay("done", 2)) is False
    assert ocr_job.blocks_credit(pay("pending", 90)) is False  # a dead queue cannot park the money forever
    cfg = dict(provisional.DEFAULT, enabled=True)
    assert await provisional._block_reason(None, pay("pending", 2), cfg, []) == "ocr_pending"


async def test_known_duplicate_verdict_wins_over_a_pending_reading():
    """A fingerprint verdict is already known at upload time; waiting for OCR must not mask it behind ``ocr_pending``."""
    from types import SimpleNamespace

    from melorin.core.db import utcnow
    from melorin.modules.payments import provisional

    pay = SimpleNamespace(
        amount=150_000,
        currency="IRT",
        meta={
            "receipt_ocr": {"state": "pending", "queued_at": utcnow().isoformat()},
            "receipt_claim": {"reference": "123456789"},
            "receipt_duplicate": {"payments": [{"id": "x", "status": "succeeded"}], "other_stores": []},
        },
    )
    cfg = dict(provisional.DEFAULT, enabled=True)
    assert await provisional._block_reason(None, pay, cfg, []) == "duplicate_image"


async def test_same_network_cannot_open_many_provisional_credits_or_reuse_after_revoke():
    """A fresh account from a network that already holds open / revoked credits is left to a human (V-022)."""
    from types import SimpleNamespace

    from melorin.modules.payments import provisional

    tag = provisional.origin_tag("203.0.113.7")
    assert tag == provisional.origin_tag("203.0.113.7") and tag != provisional.origin_tag("203.0.113.8")

    def pay(i, state=None, origin=tag):
        meta = {"receipt_claim": {"reference": f"ref-{i}"}, "receipt_origin": origin}
        if state:
            meta["provisional"] = {"state": state}
        return SimpleNamespace(id=i, user_id=i, amount=150_000, currency="IRT", meta=meta, receipt_file_id=None)

    cfg = dict(provisional.DEFAULT, enabled=True, min_account_age_hours=0, max_open_per_origin=2)
    me = pay(10)
    assert await provisional._block_reason(None, me, cfg, [me]) is None
    two_open = [pay(1, "open"), pay(2, "open"), me]
    assert await provisional._block_reason(None, me, cfg, two_open) == "origin_open_limit"
    assert await provisional._block_reason(None, me, cfg, [pay(3, "revoked"), me]) == "origin_revoked_before"
    assert await provisional._block_reason(None, me, cfg, [pay(1, "open"), pay(4, "open", origin="other"), me]) is None
