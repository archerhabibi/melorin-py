"""Telegram login is configured from the admin panel (Settings > Telegram login) and the OIDC flow it enables."""

import json
import time
import types
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy import select

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import config as config_mod
from melorin.core import db, integrations, ratelimit
from melorin.core.deps import get_session
from melorin.core.errors import AppError, install
from melorin.modules.admin import integrations as admin_integrations
from melorin.modules.identity import service
from melorin.channels.telegram import oidc
from melorin.channels.telegram import web
from melorin.kernel.models.identity import Identity, RefreshToken, TelegramLoginSession, User
from melorin.modules.identity.schemas import TelegramProfile
from melorin.channels.telegram.oidc_router import tgoidc
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent, FeatureFlag, SecurityEvent, SystemSetting

TABLES = [
    User.__table__,
    Identity.__table__,
    RefreshToken.__table__,
    Store.__table__,
    TelegramLoginSession.__table__,
    AuditEvent.__table__,
    SecurityEvent.__table__,
    FeatureFlag.__table__,
    SystemSetting.__table__,
]
ADMIN = types.SimpleNamespace(id=None)
CLIENT_ID = "123456789"
START, CALLBACK = "/api/v1/auth/telegram/oidc/start", "/api/v1/auth/telegram/oidc/callback"


@pytest.fixture
async def world(tmp_path, monkeypatch):
    monkeypatch.delenv("MELORIN_TELEGRAM_WEB_LOGIN_TTL_SECONDS", raising=False)
    config_mod.get_settings.cache_clear()
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/tgl.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))
    monkeypatch.setattr(ratelimit, "get_redis", lambda: None)
    ratelimit._mem.clear()
    async with db.session_factory()() as s:
        main = Store(kind="main", name="Main", slug="main", bot_username="melorin_bot")
        s.add(main)
        await s.commit()
        yield types.SimpleNamespace(s=s, main=main)
    await db.engine().dispose()
    config_mod.get_settings.cache_clear()


async def save(s, **kw):
    body = {"enabled": True, "oidc_login": True, "client_id": CLIENT_ID, "client_secret": "s3cret-from-botfather", **kw}
    return await admin_integrations.update_telegram(admin_integrations.TelegramIn(**body), ADMIN, s)


# ---------------- settings ----------------
async def test_defaults_keep_previous_behaviour(world):
    cfg = await integrations.get_telegram(world.s)
    assert cfg["source"] == "default" and integrations.telegram_bot_ready(cfg) and not integrations.telegram_oidc_ready(cfg)
    assert integrations.telegram_ttl(cfg) == 180 and cfg["number_match"] is True
    assert integrations.public_telegram(cfg) == {"bot_login": True, "oidc_login": False}


async def test_update_validates_input(world):
    bad = [
        (dict(client_id="abc"), "TELEGRAM_CLIENT_ID_INVALID"),
        (dict(client_id=""), "TELEGRAM_CONFIG_INCOMPLETE"),
        (dict(client_secret=None), "TELEGRAM_CONFIG_INCOMPLETE"),
        (dict(bot_login=False, oidc_login=False), "TELEGRAM_NO_METHOD"),
    ]
    for kw, code in bad:
        with pytest.raises(AppError) as e:
            await save(world.s, **kw)
        assert e.value.code == code
    with pytest.raises(Exception):  # TTL outside 60..600 is rejected by the schema
        admin_integrations.TelegramIn(enabled=True, ttl_seconds=5)


async def test_secret_is_encrypted_at_rest_and_never_returned(world):
    out = await save(world.s)
    assert (
        out["client_secret_set"] is True
        and "client_secret" not in out
        and "client_secret_enc" not in out
        and "s3cret" not in json.dumps(out)
    )
    raw = await world.s.scalar(select(SystemSetting.value).where(SystemSetting.key == integrations.TELEGRAM_KEY))
    assert "s3cret" not in json.dumps(raw) and raw["client_secret_enc"]
    cfg = await integrations.get_telegram(world.s)
    assert integrations.telegram_client_secret(cfg) == "s3cret-from-botfather" and integrations.telegram_oidc_ready(cfg)
    assert "client_id" not in integrations.public_telegram(cfg)
    audit = (await world.s.scalars(select(AuditEvent).where(AuditEvent.action == "integration.telegram.updated"))).all()
    assert audit and "s3cret" not in json.dumps([a.data for a in audit])
    # None keeps, "" clears
    await save(world.s, client_secret=None)
    assert integrations.telegram_client_secret(await integrations.get_telegram(world.s)) == "s3cret-from-botfather"
    await save(world.s, oidc_login=False, client_secret="")
    cfg = await integrations.get_telegram(world.s)
    assert not cfg["client_secret_enc"] and not integrations.telegram_oidc_ready(cfg)


async def test_panel_switches_drive_the_bot_approval_flow(world):
    await save(world.s, bot_login=True, number_match=False, ttl_seconds=90)
    cfg = await integrations.get_telegram(world.s)
    assert web.ttl_seconds(cfg) == 90 and web.number_match_enabled(cfg) is False
    started = await web.create_session(world.s, world.main, ip="203.0.113.7", user_agent="x")
    assert 85 <= web.seconds_left(started.row) <= 90
    await save(world.s, bot_login=False)
    with pytest.raises(AppError) as e:
        await web.create_session(world.s, world.main, ip="203.0.113.7", user_agent="x")
    assert e.value.code == "TELEGRAM_LOGIN_UNAVAILABLE"
    await save(world.s, bot_login=True, enabled=False)  # master switch off
    with pytest.raises(AppError):
        await web.create_session(world.s, world.main, ip="203.0.113.7", user_agent="x")


async def test_disabling_mid_flight_closes_the_open_request(world):
    started = await web.create_session(world.s, world.main, ip="203.0.113.7", user_agent="x")
    await save(world.s, enabled=False)
    out = await web.decide(world.s, started.row.public_id, world.main.id, TelegramProfile(telegram_id=7), "approve", None)
    assert out == {"result": "denied", "reason": "login_disabled"}


# ---------------- OIDC primitives ----------------
@pytest.fixture
def signer(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())) | {"kid": "k1", "alg": "RS256", "use": "sig"}

    async def fetch():
        return {"keys": [jwk]}

    monkeypatch.setattr(oidc, "fetch_jwks", fetch)
    oidc._jwks_cache.update(at=0.0, keys={})

    def make(signing_key=key, headers=None, **over):
        now = int(time.time())
        claims = {
            "iss": oidc.ISSUER,
            "aud": CLIENT_ID,
            "sub": "9990001",
            "iat": now,
            "exp": now + 600,
            "id": 555001,
            "name": "Ali Rezaei",
            "given_name": "Ali",
            "family_name": "Rezaei",
            "preferred_username": "ali_r",
        } | over
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, signing_key, algorithm="RS256", headers=headers or {"kid": "k1"})

    return types.SimpleNamespace(make=make)


async def test_id_token_validation(signer):
    claims = await oidc.verify_id_token(signer.make(nonce="n1"), CLIENT_ID, "n1")
    assert oidc.profile_from_claims(claims) == TelegramProfile(telegram_id=555001, first_name="Ali", last_name="Rezaei", username="ali_r")
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad = [
        signer.make(aud="999"),
        signer.make(iss="https://evil.example"),
        signer.make(exp=int(time.time()) - 3600),
        signer.make(signing_key=other),
        signer.make(nonce="other"),
        signer.make(headers={"kid": "unknown"}),
        jwt.encode(
            {"iss": oidc.ISSUER, "aud": CLIENT_ID, "sub": "1", "iat": 1, "exp": 4102444800},
            "x" * 40,
            algorithm="HS256",
            headers={"kid": "k1"},
        ),
    ]
    for tok in bad:
        with pytest.raises(AppError) as e:
            await oidc.verify_id_token(tok, CLIENT_ID, "n1")
        assert e.value.code == "TELEGRAM_OIDC_INVALID"
    with pytest.raises(AppError) as e:  # without the profile scope there is no real Telegram ID: never fall back to ``sub``
        oidc.profile_from_claims(await oidc.verify_id_token(signer.make(id=None), CLIENT_ID))
    assert e.value.code == "TELEGRAM_OIDC_NO_ID"


def test_flow_cookie_cannot_be_confused_with_an_access_token():
    sealed = oidc.seal(state="s")
    assert oidc.unseal(sealed)["state"] == "s" and oidc.unseal(sealed + "x") is None and oidc.unseal(None) is None
    from melorin.core.security import create_access_token, decode_access_token

    assert oidc.unseal(create_access_token(__import__("uuid").uuid4(), False)[0]) is None  # access token is not a flow cookie
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(sealed)  # and the flow cookie is not an access token (no ``sub``)


def test_bot_id_is_the_client_id():
    assert oidc.bot_id_of("123456789:AAH-secret") == "123456789" and oidc.bot_id_of("garbage") is None and oidc.bot_id_of(None) is None


# ---------------- HTTP flow ----------------
@pytest.fixture
async def http(world):
    app = FastAPI()
    install(app)
    app.include_router(tgoidc, prefix="/api/v1")

    async def override():
        async with db.session_factory()() as s:
            yield s

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def begin(http):
    r = await http.get(START)
    assert r.status_code == 303
    url = urlparse(r.headers["location"])
    return r, {k: v[0] for k, v in parse_qs(url.query).items()}, oidc.unseal(http.cookies.get(oidc.COOKIE))


def stub_exchange(monkeypatch, token):
    calls = []

    async def fake(client_id, secret, code, redirect, verifier):
        calls.append(dict(client_id=client_id, secret=secret, code=code, redirect=redirect, verifier=verifier))
        return token() if callable(token) else token

    monkeypatch.setattr(oidc, "exchange_code", fake)
    return calls


async def test_public_config_reflects_the_panel(http, world):
    assert (await http.get("/api/v1/auth/telegram/config")).json() == {"bot_login": True, "oidc_login": False}
    r = await http.get("/api/v1/auth/telegram/config")
    assert r.headers["cache-control"] == "no-store"
    await save(world.s)
    assert (await http.get("/api/v1/auth/telegram/config")).json() == {"bot_login": True, "oidc_login": True}


async def test_start_is_unavailable_until_configured(http, world):
    r = await http.get(START)
    assert r.status_code == 303 and r.headers["location"].endswith("/?tg_error=unavailable")


async def test_start_builds_a_pkce_authorize_url_and_a_one_shot_cookie(http, world):
    await save(world.s)
    r, q, flow = await begin(http)
    assert r.headers["location"].startswith("https://oauth.telegram.org/auth?") and r.headers["cache-control"] == "no-store"
    assert q["client_id"] == CLIENT_ID and q["response_type"] == "code" and q["scope"] == "openid profile"
    assert q["redirect_uri"] == "http://localhost:3000" + oidc.CALLBACK_PATH and q["code_challenge_method"] == "S256"
    assert q["state"] == flow["state"] and q["nonce"] == flow["nonce"] and q["code_challenge"] != flow["cv"]
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()


async def test_successful_login_maps_to_the_same_account_as_the_bot(http, world, signer, monkeypatch):
    await save(world.s)
    existing, _ = await service.login_with_telegram(world.s, TelegramProfile(telegram_id=555001, first_name="Ali"))
    await world.s.commit()
    _, q, flow = await begin(http)
    calls = stub_exchange(monkeypatch, lambda: signer.make(nonce=flow["nonce"]))
    r = await http.get(CALLBACK, params={"code": "abc", "state": q["state"]})
    assert r.status_code == 303 and r.headers["location"] == "http://localhost:3000/#/dashboard"
    assert calls == [
        dict(
            client_id=CLIENT_ID,
            secret="s3cret-from-botfather",  # pragma: allowlist secret
            code="abc",
            redirect="http://localhost:3000" + oidc.CALLBACK_PATH,
            verifier=flow["cv"],
        )
    ]
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("melorin_refresh=") for c in cookies)
    assert any(
        c.startswith(f"{oidc.COOKIE}=") and ("max-age=0" in c.lower() or "expires=" in c.lower()) for c in cookies
    )  # flow cookie cleared
    tokens = (await world.s.scalars(select(RefreshToken))).all()
    assert len(tokens) == 1 and tokens[0].user_id == existing.id
    assert len((await world.s.scalars(select(Identity).where(Identity.provider == "telegram"))).all()) == 1


async def test_new_customer_gets_an_account(http, world, signer, monkeypatch):
    await save(world.s)
    _, q, flow = await begin(http)
    stub_exchange(monkeypatch, lambda: signer.make(nonce=flow["nonce"], id=777001))
    r = await http.get(CALLBACK, params={"code": "abc", "state": q["state"]})
    assert r.headers["location"].endswith("/#/dashboard")
    assert await service.find_identity(world.s, "telegram", "777001") is not None


@pytest.mark.parametrize("tamper", ["state", "no_cookie", "aud", "expired", "no_id", "denied", "no_code"])
async def test_rejections_end_in_a_safe_redirect_and_issue_nothing(http, world, signer, monkeypatch, tamper):
    await save(world.s)
    _, q, flow = await begin(http)
    token = {
        "aud": lambda: signer.make(aud="1", nonce=flow["nonce"]),
        "expired": lambda: signer.make(exp=int(time.time()) - 900, nonce=flow["nonce"]),
        "no_id": lambda: signer.make(id=None, nonce=flow["nonce"]),
    }.get(tamper, lambda: signer.make(nonce=flow["nonce"]))
    calls = stub_exchange(monkeypatch, token)
    params = {"code": "abc", "state": q["state"]}
    if tamper == "state":
        params["state"] = "forged"
    if tamper == "no_cookie":
        http.cookies.clear()
    if tamper == "denied":
        params = {"error": "access_denied", "state": q["state"]}
    if tamper == "no_code":
        params = {"state": q["state"]}
    r = await http.get(CALLBACK, params=params)
    reason = {"no_cookie": "session_expired", "denied": "user_denied"}.get(tamper, "failed")
    assert r.status_code == 303 and r.headers["location"] == f"http://localhost:3000/?tg_error={reason}"
    assert not (await world.s.scalars(select(RefreshToken))).all() and not any(
        c.startswith("melorin_refresh=") for c in r.headers.get_list("set-cookie")
    )
    if tamper in ("state", "no_cookie", "denied", "no_code"):
        assert calls == []  # the code is never exchanged unless the browser-bound state matches
    if tamper == "state":
        assert (await world.s.scalars(select(SecurityEvent).where(SecurityEvent.kind == "tg_oidc_state_mismatch"))).all()


async def test_admins_and_inactive_accounts_never_get_a_session(http, world, signer, monkeypatch):
    await save(world.s)
    for tg_id, reason, flag in ((555001, "admin_use_panel", "is_super_admin"), (555002, "account_disabled", "is_active")):
        user, _ = await service.login_with_telegram(world.s, TelegramProfile(telegram_id=tg_id, first_name="X"))
        setattr(user, flag, True if flag == "is_super_admin" else False)
        await world.s.commit()
        http.cookies.clear()
        _, q, flow = await begin(http)
        stub_exchange(monkeypatch, lambda tg_id=tg_id, flow=flow: signer.make(nonce=flow["nonce"], id=tg_id))
        r = await http.get(CALLBACK, params={"code": "abc", "state": q["state"]})
        assert r.headers["location"] == f"http://localhost:3000/?tg_error={reason}"
    assert not (await world.s.scalars(select(RefreshToken))).all()


async def test_closed_registration_blocks_new_accounts_only(http, world, signer, monkeypatch):
    await save(world.s)
    await service.login_with_telegram(world.s, TelegramProfile(telegram_id=555001, first_name="Known"))
    world.s.add(FeatureFlag(key="registration", scope_type="global", scope_id="*", enabled=False))
    await world.s.commit()
    for tg_id, expect in ((888001, "?tg_error=registration_closed"), (555001, "#/dashboard")):
        http.cookies.clear()
        _, q, flow = await begin(http)
        stub_exchange(monkeypatch, lambda tg_id=tg_id, flow=flow: signer.make(nonce=flow["nonce"], id=tg_id))
        r = await http.get(CALLBACK, params={"code": "abc", "state": q["state"]})
        assert r.headers["location"].endswith(expect)


async def test_emergency_bot_flag_closes_the_flow(http, world):
    await save(world.s)
    world.s.add(FeatureFlag(key="bot", scope_type="global", scope_id="*", enabled=False))
    await world.s.commit()
    r = await http.get(START)
    assert r.headers["location"].endswith("/?tg_error=unavailable")


async def test_panel_test_endpoint_reports_without_leaking_secrets(world, monkeypatch):
    await save(world.s)

    class Resp:
        def __init__(self, status=200, body=None):
            self.status_code, self._b, self.headers = status, body or {}, {"content-type": "application/json"}

        def json(self):
            return self._b

    class Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            if url.endswith("openid-configuration"):
                return Resp(body={"issuer": oidc.ISSUER})
            if url.endswith("jwks.json"):
                return Resp(body={"keys": [{"kid": "k1"}]})
            return Resp(status=200, body={"result": {"username": "melorin_bot"}})

        async def post(self, url, **k):
            return Resp(status=401, body={"error": "invalid_client"})

    monkeypatch.setattr(admin_integrations.httpx, "AsyncClient", Client)
    monkeypatch.setattr(config_mod.get_settings(), "main_bot_token", "123456789:AAFakeToken")
    out = await admin_integrations.test_telegram(ADMIN, world.s)
    by = {c["key"]: c for c in out["checks"]}
    assert by["discovery"]["status"] == "ok" and by["jwks"]["status"] == "ok" and by["bot"]["status"] == "ok"
    assert by["credentials"]["status"] == "fail" and out["ok"] is False
    assert "AAFakeToken" not in json.dumps(out) and "s3cret" not in json.dumps(out)


# ---------------- main bot username ----------------
async def test_main_bot_username_autodetect_manual_and_guards(world, monkeypatch):
    # BotStoreBinding declares its owner index twice (column index=True + explicit Index), so create_all fails on SQLite:
    # a minimal table is enough for this test.
    async with db.engine().begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE bot_store_bindings (id CHAR(32), bot_key VARCHAR(120), bot_username VARCHAR(100), store_id CHAR(32), owner_user_id CHAR(32), "
            "bot_kind VARCHAR(20), status VARCHAR(20), config JSON, created_at DATETIME, updated_at DATETIME)"
        )
    world.main.bot_username = None
    await world.s.commit()

    async def fake(real):
        async def f(token):
            return True, real

        return f

    orig = admin_integrations._main_bot

    async def with_token(s):  # pretend a token exists; keep the real stored username
        return "123:abc", (await orig(s))[1]

    monkeypatch.setattr(admin_integrations, "_main_bot", with_token)
    monkeypatch.setattr(admin_integrations, "_bot_get_me", await fake("meeloorin_bot"))
    put = lambda u: admin_integrations.set_main_bot_username(admin_integrations.MainBotIn(username=u), ADMIN, world.s)
    out = await put(None)  # auto-detect from the token
    assert out["main_bot_username"] == "meeloorin_bot"
    out = await put("@Meeloorin_Bot")  # manual, case-insensitive match with the real bot
    assert out["main_bot_username"] == "Meeloorin_Bot"
    with pytest.raises(AppError) as e:
        await put("other_bot")
    assert e.value.code == "BOT_USERNAME_MISMATCH"
    with pytest.raises(AppError) as e:
        await put("a b")
    assert e.value.code == "BOT_USERNAME_INVALID"
    world.s.add(Store(kind="reseller", name="R", slug="r", bot_username="meeloorin_bot2"))
    await world.s.commit()
    monkeypatch.setattr(admin_integrations, "_bot_get_me", await fake("meeloorin_bot2"))
    with pytest.raises(AppError) as e:
        await put("meeloorin_bot2")
    assert e.value.code == "BOT_USERNAME_TAKEN"
    cfg = await integrations.get_telegram(world.s)
    assert integrations.telegram_bot_ready(cfg)
