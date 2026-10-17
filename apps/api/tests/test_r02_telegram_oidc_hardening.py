# ruff: noqa: F811  (pytest fixtures imported from the R01 module are used as arguments)
"""Hardening of the Telegram login pass (R02): flow-cookie key separation, error classification, panel diagnostics, UI contract."""
import json
import pathlib

import httpx
import jwt
import pytest
from sqlalchemy import select

from melorin.core import config as config_mod
from melorin.core.errors import AppError
from melorin.modules.admin import integrations as admin_integrations
from melorin.modules.identity import telegram_oidc as oidc
from melorin.modules.stores.models import Store
from melorin.modules.system.models import SecurityEvent

from tests.test_r01_telegram_login_settings import ADMIN, CALLBACK, CLIENT_ID, begin, http, save, signer, stub_exchange, world  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[3]


# ---------------- flow cookie ----------------
def test_flow_cookie_uses_its_own_derived_key():
    sealed = oidc.seal(state="s", nonce="n")
    with pytest.raises(jwt.PyJWTError):  # not verifiable with the shared app secret ...
        jwt.decode(sealed, config_mod.get_settings().jwt_secret, algorithms=["HS256"])
    # ... and a cookie forged with the app secret (e.g. from a leaked/guessed access-token key use) is rejected
    forged = jwt.encode({"state": "s", "typ": "tg_oidc_flow", "exp": 4102444800}, config_mod.get_settings().jwt_secret, algorithm="HS256")
    assert oidc.unseal(forged) is None and oidc.unseal(sealed)["nonce"] == "n"


# ---------------- token endpoint classification ----------------
def patch_token_endpoint(monkeypatch, status, body):
    real = httpx.AsyncClient

    def handler(request):
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    monkeypatch.setattr(oidc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))


@pytest.mark.parametrize("status,body,code", [
    (503, "upstream down", "TELEGRAM_OIDC_UNREACHABLE"),
    (401, {"error": "invalid_client"}, "TELEGRAM_OIDC_CLIENT_REJECTED"),
    (400, {"error": "invalid_client"}, "TELEGRAM_OIDC_CLIENT_REJECTED"),
    (400, {"error": "invalid_grant"}, "TELEGRAM_OIDC_EXCHANGE_FAILED"),
    (400, "<html>not json</html>", "TELEGRAM_OIDC_EXCHANGE_FAILED"),
    (200, "not json", "TELEGRAM_OIDC_EXCHANGE_FAILED"),
    (200, {"access_token": "x"}, "TELEGRAM_OIDC_EXCHANGE_FAILED"),
])
async def test_exchange_code_classifies_failures(monkeypatch, status, body, code):
    patch_token_endpoint(monkeypatch, status, body)
    with pytest.raises(AppError) as e:
        await oidc.exchange_code(CLIENT_ID, "secret", "code", "https://x/cb", "v" * 43)
    assert e.value.code == code


async def test_exchange_code_sends_basic_auth_pkce_and_returns_the_id_token(monkeypatch):
    seen = {}
    real = httpx.AsyncClient

    def handler(request):
        seen["auth"], seen["body"] = request.headers.get("authorization"), request.content.decode()
        return httpx.Response(200, json={"id_token": "tok", "access_token": "a"})

    monkeypatch.setattr(oidc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    assert await oidc.exchange_code(CLIENT_ID, "secret", "abc", "https://x/cb", "ver" * 15) == "tok"
    assert seen["auth"].startswith("Basic ") and "code_verifier=" in seen["body"] and "grant_type=authorization_code" in seen["body"]


async def test_rejected_client_credentials_are_logged_for_the_admin_and_hidden_from_the_customer(http, world, monkeypatch):
    await save(world.s)
    _, q, _flow = await begin(http)

    async def rejected(*a, **k):
        raise AppError("TELEGRAM_OIDC_CLIENT_REJECTED", "x", 502, {"telegram_error": "invalid_client"})

    monkeypatch.setattr(oidc, "exchange_code", rejected)
    r = await http.get(CALLBACK, params={"code": "abc", "state": q["state"]})
    assert r.headers["location"].endswith("/?tg_error=unavailable")  # the customer is not told about credentials
    ev = (await world.s.scalars(select(SecurityEvent).where(SecurityEvent.kind == "tg_oidc_rejected"))).all()
    assert ev and ev[-1].data == {"code": "TELEGRAM_OIDC_CLIENT_REJECTED", "telegram_error": "invalid_client"}


async def test_telegram_outage_is_reported_as_unreachable(http, world, monkeypatch):
    await save(world.s)
    _, q, _flow = await begin(http)

    async def down(*a, **k):
        raise AppError("TELEGRAM_OIDC_UNREACHABLE", "x", 502)

    monkeypatch.setattr(oidc, "exchange_code", down)
    r = await http.get(CALLBACK, params={"code": "abc", "state": q["state"]})
    assert r.headers["location"].endswith("/?tg_error=unreachable")


# ---------------- panel diagnostics ----------------
class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b, self.headers = status, body if body is not None else {}, {"content-type": "application/json"}

    def json(self):
        if self._b == "bad":
            raise ValueError("no json")
        return self._b


def fake_client(token_resp, bot="melorin_bot"):
    class Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, url, **k):
            if url.endswith("openid-configuration"):
                return Resp(body={"issuer": oidc.ISSUER})
            if url.endswith("jwks.json"):
                return Resp(body={"keys": [{"kid": "k1"}]})
            return Resp(body={"result": {"username": bot}})

        async def post(self, url, **k):
            return token_resp

    return Client


async def run_test(world, monkeypatch, token_resp=None, **kw):
    monkeypatch.setattr(admin_integrations.httpx, "AsyncClient", fake_client(token_resp or Resp(400, {"error": "invalid_grant"})))
    monkeypatch.setattr(config_mod.get_settings(), "main_bot_token", "123456789:AAFakeToken")
    return {c["key"]: c for c in (await admin_integrations.test_telegram(ADMIN, world.s))["checks"]}


async def test_panel_test_accepts_a_healthy_setup(world, monkeypatch):
    await save(world.s)
    by = await run_test(world, monkeypatch)
    assert by["credentials"]["status"] == "ok" and by["bot"]["status"] == "ok" and by["client_id"]["status"] == "ok"


@pytest.mark.parametrize("resp,status", [(Resp(500, {}), "warn"), (Resp(400, "bad"), "ok"), (Resp(401, "bad"), "fail")])
async def test_panel_test_credential_check_is_robust(world, monkeypatch, resp, status):
    await save(world.s)
    assert (await run_test(world, monkeypatch, resp))["credentials"]["status"] == status  # never a 500 on odd Telegram replies


async def test_panel_test_flags_a_missing_bot_username(world, monkeypatch):
    await save(world.s)
    main = await world.s.scalar(select(Store).where(Store.kind == "main"))
    main.bot_username = None
    await world.s.commit()
    by = await run_test(world, monkeypatch)
    assert by["bot"]["status"] == "fail" and "@melorin_bot" in by["bot"]["message"]


async def test_panel_test_requires_a_public_https_site_in_production(world, monkeypatch):
    await save(world.s)
    by = await run_test(world, monkeypatch)
    assert by["site_url"]["status"] == "warn"  # dev: localhost tolerated
    monkeypatch.setattr(type(config_mod.get_settings()), "is_dev", property(lambda self: False))
    by = await run_test(world, monkeypatch)
    assert by["site_url"]["status"] == "fail" and "MELORIN_STORE_WEB_URL" in by["site_url"]["message"]
    monkeypatch.setenv("MELORIN_STORE_WEB_URL", "https://shop.example.com")
    config_mod.get_settings.cache_clear()
    monkeypatch.setattr(type(config_mod.get_settings()), "is_dev", property(lambda self: False))
    by = await run_test(world, monkeypatch)
    assert by["site_url"]["status"] == "ok" and "https://shop.example.com/api/v1/auth/telegram/oidc/callback" in by["site_url"]["message"]


async def test_panel_test_explains_switched_off_states(world, monkeypatch):
    await save(world.s, enabled=False)
    assert (await run_test(world, monkeypatch))["enabled"]["status"] == "warn"
    await save(world.s, enabled=True, store_login=False)
    assert (await run_test(world, monkeypatch))["store_login"]["status"] == "warn"


# ---------------- UI contract ----------------
def test_storefront_uses_the_shared_buttons_and_retries_after_a_failed_redirect():
    app = (ROOT / "apps/store-web/src/App.jsx").read_text(encoding="utf-8")
    assert 'import TelegramLoginButtons from "./TelegramLoginButtons.jsx"' in app and "<TelegramLoginButtons" in app
    assert "TG_RETRY" in app and 'setModal("login")' in app and "origin_mismatch" in app
    btn = (ROOT / "apps/store-web/src/TelegramLoginButtons.jsx").read_text(encoding="utf-8")
    assert "/api/v1/auth/telegram/oidc/start?store_id=" in btn and "pageshow" in btn and "btn-tg" in btn


def test_admin_panel_describes_saved_state_and_guards_unsaved_edits():
    src = (ROOT / "apps/admin-web/src/TelegramLoginSettings.jsx").read_text(encoding="utf-8")
    assert "const dirty" in src and "تغییرات ذخیره‌نشده" in src and "botReady" in src and "oidcReady" in src and "ttlError" in src
    assert "saved.store_login" in src  # the badge honours the storefront switch, like the server's public_telegram()
