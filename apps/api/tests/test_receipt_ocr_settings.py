"""Receipt OCR is configured from the admin panel: encrypted key, validation, live test, and the reader obeys it."""

import types
import uuid

import httpx
import pytest
from sqlalchemy import select

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import config as config_mod
from melorin.core import db, integrations
from melorin.core.errors import AppError
from melorin.kernel.models.system import AuditEvent, SystemSetting
from melorin.modules.admin.integrations import receipt_ocr as admin_ocr
from melorin.modules.admin.integrations.schemas import ReceiptOcrIn
from melorin.modules.payments import receipt_ocr

ADMIN = types.SimpleNamespace(id=uuid.UUID("00000000-0000-0000-0000-000000000001"))
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


@pytest.fixture
async def session(tmp_path, monkeypatch):
    for k in ("ENGINE", "API_KEY", "MODEL"):
        monkeypatch.delenv(f"MELORIN_RECEIPT_OCR_{k}", raising=False)
    config_mod.get_settings.cache_clear()
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/o.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[SystemSetting.__table__, AuditEvent.__table__]))
    async with db.session_factory()() as s:
        yield s
    await db.engine().dispose()
    config_mod.get_settings.cache_clear()


async def test_without_a_saved_config_the_environment_still_decides(session, monkeypatch):
    monkeypatch.setenv("MELORIN_RECEIPT_OCR_ENGINE", "vision")
    monkeypatch.setenv("MELORIN_RECEIPT_OCR_API_KEY", "env-key")
    config_mod.get_settings.cache_clear()
    cfg = await integrations.get_receipt_ocr(session)
    assert cfg["source"] == "env" and receipt_ocr.configured_engine(receipt_ocr.resolve(cfg)) == "vision"


async def test_save_encrypts_the_key_and_never_returns_it(session):
    out = await admin_ocr.update_receipt_ocr(
        ReceiptOcrIn(engine="vision", api_key="sk-secret-123", model="claude-haiku-5-5"), ADMIN, session
    )
    assert out["api_key_set"] is True and "sk-secret-123" not in str(out) and out["active_engine"] == "vision"
    raw = (await session.scalars(select(SystemSetting))).one().value
    assert "sk-secret-123" not in str(raw) and raw["api_key_enc"]
    audit = " ".join(str(a.data) for a in (await session.scalars(select(AuditEvent))).all())
    assert "sk-secret-123" not in audit and "key_changed" in audit
    # Omitting the key keeps it; an empty string clears it.
    kept = await admin_ocr.update_receipt_ocr(ReceiptOcrIn(engine="vision"), ADMIN, session)
    assert kept["api_key_set"] is True
    with pytest.raises(AppError) as e:
        await admin_ocr.update_receipt_ocr(ReceiptOcrIn(engine="vision", api_key=""), ADMIN, session)
    assert e.value.code == "OCR_KEY_REQUIRED"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"engine": "magic"}, "OCR_ENGINE_INVALID"),
        ({"engine": "auto", "base_url": "http://insecure.example"}, "OCR_BASE_URL_INVALID"),
        ({"engine": "tesseract", "tesseract_lang": "fas; rm -rf /"}, "OCR_LANG_INVALID"),
    ],
)
async def test_validation(session, body, code):
    with pytest.raises(AppError) as e:
        await admin_ocr.update_receipt_ocr(ReceiptOcrIn(**body), ADMIN, session)
    assert e.value.code == code


async def test_the_reader_uses_the_panel_config_not_the_environment(session, monkeypatch):
    await admin_ocr.update_receipt_ocr(ReceiptOcrIn(engine="vision", api_key="panel-key", model="m-panel"), ADMIN, session)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"], seen["model"] = request.headers["x-api-key"], request.read().decode()
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"amount_rial": 1500000}'}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(receipt_ocr.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    cfg = receipt_ocr.resolve(await integrations.get_receipt_ocr(session))
    facts, engine = await receipt_ocr.read_receipt(PNG, "image/png", cfg)
    assert engine == "vision" and facts.amount_rial == 1_500_000
    assert seen["key"] == "panel-key" and "m-panel" in seen["model"]


@pytest.mark.parametrize(("status", "ok", "needle"), [(200, True, "تأیید"), (401, False, "کلید"), (404, False, "مدل"), (429, False, "سقف")])
async def test_connection_test_explains_the_failure(session, monkeypatch, status, ok, needle):
    await admin_ocr.update_receipt_ocr(ReceiptOcrIn(engine="vision", api_key="k"), ADMIN, session)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        admin_ocr.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={})), **kw)
    )
    out = await admin_ocr.test_receipt_ocr(ADMIN, session)
    assert out["ok"] is ok and needle in (out["detail"] or out["error"])
