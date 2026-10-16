"""Website login approved in the Telegram bot: lifecycle, anti-phishing rules and the real HTTP surface."""
import datetime as dt
import types

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db, ratelimit
from melorin.core.config import get_settings
from melorin.core.db import utcnow
from melorin.core.deps import get_session
from melorin.core.errors import AppError, install
from melorin.modules.identity import telegram_web as web
from melorin.modules.identity.models import Identity, RefreshToken, TelegramLoginSession, User
from melorin.modules.identity.schemas import TelegramProfile
from melorin.modules.identity.telegram_web_router import tgweb
from melorin.modules.stores.models import Store
from melorin.modules.system.models import AuditEvent, FeatureFlag, SecurityEvent

TABLES = [User.__table__, Identity.__table__, RefreshToken.__table__, Store.__table__, TelegramLoginSession.__table__, AuditEvent.__table__, SecurityEvent.__table__, FeatureFlag.__table__]
BOT = {"X-Bot-Secret": get_settings().bot_service_secret}
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def prof(tid=111, **kw):
    return TelegramProfile(telegram_id=tid, first_name=kw.pop("first_name", "Ali"), **kw)


@pytest.fixture
async def world(tmp_path, monkeypatch):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/tgweb.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))
    monkeypatch.setattr(ratelimit, "get_redis", lambda: None)  # deterministic in-process limiter
    ratelimit._mem.clear()
    async with db.session_factory()() as s:
        main = Store(kind="main", name="Main", slug="main", bot_username="@melorin_bot")
        other = Store(kind="reseller", name="Shop", slug="shop", bot_username="shop_bot")
        nobot = Store(kind="reseller", name="NoBot", slug="nobot")
        s.add_all([main, other, nobot])
        await s.commit()
        yield types.SimpleNamespace(s=s, main=main, other=other, nobot=nobot)
    await db.engine().dispose()


async def _start(w, store=None):
    return await web.create_session(w.s, store or w.main, ip="203.0.113.7", user_agent=CHROME)


async def _row(w, started):
    return await w.s.scalar(select(TelegramLoginSession).where(TelegramLoginSession.public_id == started.row.public_id).execution_options(populate_existing=True))


# ---------------- service ----------------
async def test_session_is_created_with_hashed_poll_token_and_context(world):
    st = await _start(world)
    row = await _row(world, st)
    assert st.bot_username == "melorin_bot"  # "@" stripped
    assert row.secret_hash != st.poll_token and len(row.secret_hash) == 64
    assert len(row.public_id) >= 16 and row.status == "pending"
    assert row.match_code.isdigit() and len(row.match_code) == 2 and len({row.match_code, *row.decoys}) == 3
    assert row.req_device == "Chrome · Windows" and row.req_ip == "203.0.113.7"


async def test_store_without_bot_cannot_offer_telegram_login(world):
    with pytest.raises(AppError) as e:
        await _start(world, world.nobot)
    assert e.value.code == "TELEGRAM_LOGIN_UNAVAILABLE"


async def test_bot_kill_switch_blocks_new_sessions(world):
    world.s.add(FeatureFlag(key="bot", scope_type="global", scope_id="*", enabled=False))
    await world.s.commit()
    with pytest.raises(AppError) as e:
        await _start(world)
    assert e.value.code == "FEATURE_DISABLED"


async def test_happy_path_issues_tokens_once_to_the_poll_token_holder(world):
    st = await _start(world)
    info = await web.inspect(world.s, st.row.public_id, world.main.id, 111)
    assert info.status == "scanned" and st.row.match_code in web.choices_of(info) and len(web.choices_of(info)) == 3
    assert (await web.poll(world.s, st.row.public_id, st.poll_token)).status == "scanned"
    out = await web.decide(world.s, st.row.public_id, world.main.id, prof(), "approve", st.row.match_code)
    assert out == {"result": "approved"}
    res = await web.poll(world.s, st.row.public_id, st.poll_token, user_agent="pytest")
    assert res.status == "approved" and res.tokens and res.tokens.access_token and not res.tokens.is_admin
    again = await web.poll(world.s, st.row.public_id, st.poll_token)
    assert again.status == "consumed" and again.tokens is None  # single use
    user = await world.s.scalar(select(User).join(Identity).where(Identity.provider == "telegram", Identity.subject == "111"))
    assert user is not None and (await world.s.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))) is not None
    actions = set((await world.s.scalars(select(AuditEvent.action))).all())
    assert {"tg_web_login.started", "tg_web_login.approved", "tg_web_login.consumed"} <= actions


async def test_poll_requires_the_secret_not_just_the_public_id(world):
    st = await _start(world)
    await web.inspect(world.s, st.row.public_id, world.main.id, 111)
    await web.decide(world.s, st.row.public_id, world.main.id, prof(), "approve", st.row.match_code)
    for bad in ("x" * 43, st.row.public_id, "telegram-web-login-dummy"):
        with pytest.raises(AppError) as e:
            await web.poll(world.s, st.row.public_id, bad)
        assert e.value.code == "SESSION_NOT_FOUND"
    with pytest.raises(AppError):
        await web.poll(world.s, "does-not-exist-123", st.poll_token)
    assert (await web.poll(world.s, st.row.public_id, st.poll_token)).tokens is not None  # the real owner still gets in


async def test_wrong_number_twice_closes_the_session_and_alerts(world):
    st = await _start(world)
    row = await _row(world, st)
    wrong = row.decoys[0]
    r1 = await web.decide(world.s, row.public_id, world.main.id, prof(), "approve", wrong)
    assert r1["result"] == "retry" and r1["remaining"] == 1 and row.match_code in r1["choices"]
    r2 = await web.decide(world.s, row.public_id, world.main.id, prof(), "approve", wrong)
    assert r2 == {"result": "denied", "reason": "too_many_wrong_choices"}
    with pytest.raises(AppError) as e:  # even the right answer is useless afterwards
        await web.decide(world.s, row.public_id, world.main.id, prof(), "approve", row.match_code)
    assert e.value.code == "SESSION_CLOSED" and e.value.status == 410
    assert "tg_web_login_wrong_code" in (await world.s.scalars(select(SecurityEvent.kind))).all()
    assert (await world.s.scalar(select(User))) is None  # nothing was created for a failed attempt
    assert (await web.poll(world.s, row.public_id, st.poll_token)).status == "denied"


async def test_not_me_denies_and_records_a_security_event(world):
    st = await _start(world)
    out = await web.decide(world.s, st.row.public_id, world.main.id, prof(), "deny", None)
    assert out == {"result": "denied", "reason": "user_denied"}
    ev = await world.s.scalar(select(SecurityEvent).where(SecurityEvent.kind == "tg_web_login_denied_by_user"))
    assert ev and ev.data["ip"] == "203.0.113.7"
    res = await web.poll(world.s, st.row.public_id, st.poll_token)
    assert (res.status, res.reason) == ("denied", "user_denied")


async def test_expired_session_is_rejected_everywhere(world):
    st = await _start(world)
    row = await _row(world, st)
    row.expires_at = utcnow() - dt.timedelta(seconds=1)
    await world.s.commit()
    with pytest.raises(AppError) as e:
        await web.inspect(world.s, row.public_id, world.main.id, 111)
    assert e.value.code == "SESSION_CLOSED"
    assert (await web.poll(world.s, row.public_id, st.poll_token)).status == "expired"


async def test_session_is_bound_to_its_store_and_to_the_first_telegram_account(world):
    st = await _start(world)
    with pytest.raises(AppError) as e:  # a link made for the main store cannot be completed in a reseller's bot
        await web.inspect(world.s, st.row.public_id, world.other.id, 111)
    assert e.value.code == "STORE_MISMATCH"
    await web.inspect(world.s, st.row.public_id, world.main.id, 111)
    with pytest.raises(AppError) as e:  # a second account cannot take over a scanned session
        await web.inspect(world.s, st.row.public_id, world.main.id, 222)
    assert e.value.code == "SESSION_BUSY"
    with pytest.raises(AppError):
        await web.decide(world.s, st.row.public_id, world.main.id, prof(222), "approve", st.row.match_code)


async def test_super_admin_is_refused_like_the_other_storefront_logins(world):
    admin = User(display_name="Root", is_super_admin=True)
    world.s.add(admin)
    await world.s.flush()
    world.s.add(Identity(user_id=admin.id, provider="telegram", subject="999", verified_at=utcnow()))
    await world.s.commit()
    st = await _start(world)
    out = await web.decide(world.s, st.row.public_id, world.main.id, prof(999), "approve", st.row.match_code)
    assert out == {"result": "denied", "reason": "admin_use_panel"}
    assert (await web.poll(world.s, st.row.public_id, st.poll_token)).tokens is None
    assert "tg_web_login_admin_refused" in (await world.s.scalars(select(SecurityEvent.kind))).all()


async def test_disabled_account_is_refused(world):
    u = User(display_name="Off", is_active=False)
    world.s.add(u)
    await world.s.flush()
    world.s.add(Identity(user_id=u.id, provider="telegram", subject="555", verified_at=utcnow()))
    await world.s.commit()
    st = await _start(world)
    out = await web.decide(world.s, st.row.public_id, world.main.id, prof(555), "approve", st.row.match_code)
    assert out["reason"] == "account_disabled"


async def test_registration_flag_blocks_new_accounts_only(world):
    known = User(display_name="Old")
    world.s.add_all([known, FeatureFlag(key="registration", scope_type="global", scope_id="*", enabled=False)])
    await world.s.flush()
    world.s.add(Identity(user_id=known.id, provider="telegram", subject="777", verified_at=utcnow()))
    await world.s.commit()
    new = await _start(world)
    assert (await web.decide(world.s, new.row.public_id, world.main.id, prof(888), "approve", new.row.match_code))["reason"] == "registration_closed"
    assert (await world.s.scalar(select(Identity).where(Identity.subject == "888"))) is None
    old = await _start(world)
    assert (await web.decide(world.s, old.row.public_id, world.main.id, prof(777), "approve", old.row.match_code))["result"] == "approved"


async def test_number_matching_can_be_switched_off(world, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_web_login_number_match", False)
    st = await _start(world)
    assert (await web.decide(world.s, st.row.public_id, world.main.id, prof(), "approve", None))["result"] == "approved"


async def test_cancel_kills_the_link_and_purge_removes_only_old_rows(world):
    st = await _start(world)
    await web.cancel(world.s, st.row.public_id, st.poll_token)
    with pytest.raises(AppError) as e:
        await web.inspect(world.s, st.row.public_id, world.main.id, 111)
    assert e.value.code == "SESSION_CLOSED"
    with pytest.raises(AppError):
        await web.cancel(world.s, st.row.public_id, "wrong-token-wrong-token-wrong")
    old = await _start(world)
    row = await _row(world, old)
    row.expires_at = utcnow() - dt.timedelta(days=3)
    await world.s.commit()
    assert await web.purge_old(world.s) == 1
    assert (await world.s.scalar(select(TelegramLoginSession).where(TelegramLoginSession.public_id == st.row.public_id))) is not None


def test_device_label_is_coarse_and_never_raises():
    assert web.device_label("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit Version/17 Safari/604") == "Safari · iOS"
    assert web.device_label("Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0") == "Firefox · Linux"
    assert web.device_label("Mozilla/5.0 (Windows NT 10.0) Chrome/126 Safari/537 Edg/126") == "Edge · Windows"
    assert web.device_label(None) == "دستگاه ناشناس" and web.device_label("curl/8") == "دستگاه ناشناس"


# ---------------- HTTP ----------------
@pytest.fixture
async def http(world):
    app = FastAPI()
    install(app)
    app.include_router(tgweb, prefix="/api/v1")

    async def override():
        async with db.session_factory()() as s:
            yield s

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"user-agent": CHROME}) as c:
        yield c


P = "/api/v1/auth/telegram/web"


async def test_http_full_flow_sets_refresh_cookie_and_never_caches(http, world):
    r = await http.post(f"{P}/sessions", json={"store_id": str(world.main.id)})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    s = r.json()
    assert s["deeplink"] == f"https://t.me/melorin_bot?start=wl_{s['session_id']}"
    assert s["qr"].startswith("data:image/svg+xml") and len(s["match_code"]) == 2 and s["poll_interval"] == 2
    poll = lambda tok: http.post(f"{P}/sessions/{s['session_id']}/poll", json={"poll_token": tok})  # noqa: E731
    assert (await poll(s["poll_token"])).json()["status"] == "pending"
    base = {"session_id": s["session_id"], "store_id": str(world.main.id), "telegram_id": 111, "first_name": "Ali"}
    i = await http.post(f"{P}/bot/inspect", json=base, headers=BOT)
    assert i.status_code == 200 and i.json()["device"] == "Chrome · Windows" and s["match_code"] in i.json()["choices"]
    d = await http.post(f"{P}/bot/decide", json={**base, "action": "approve", "choice": s["match_code"]}, headers=BOT)
    assert d.json()["result"] == "approved"
    done = await poll(s["poll_token"])
    assert done.status_code == 200 and done.json()["tokens"]["access_token"] and "melorin_refresh" in done.headers["set-cookie"]
    assert (await poll(s["poll_token"])).json()["status"] == "consumed"
    assert (await poll("w" * 43)).status_code == 404


async def test_http_bot_endpoints_need_the_service_secret(http, world):
    s = (await http.post(f"{P}/sessions", json={})).json()  # no store_id -> main store
    body = {"session_id": s["session_id"], "store_id": str(world.main.id), "telegram_id": 1}
    assert (await http.post(f"{P}/bot/inspect", json=body)).status_code == 401
    assert (await http.post(f"{P}/bot/inspect", json=body, headers={"X-Bot-Secret": "nope"})).status_code == 401
    assert (await http.post(f"{P}/bot/decide", json={**body, "action": "approve"})).status_code == 401


async def test_http_cancel_and_rate_limit(http, world):
    s = (await http.post(f"{P}/sessions", json={})).json()
    bad = await http.post(f"{P}/sessions/{s['session_id']}/cancel", json={"poll_token": "z" * 43})
    assert bad.status_code == 404
    ok = await http.post(f"{P}/sessions/{s['session_id']}/cancel", json={"poll_token": s["poll_token"]})
    assert ok.json() == {"ok": True}
    assert (await http.post(f"{P}/sessions/{s['session_id']}/poll", json={"poll_token": s["poll_token"]})).json()["reason"] == "cancelled"
    codes = [(await http.post(f"{P}/sessions", json={})).status_code for _ in range(11)]
    assert codes[-1] == 429  # 10 sessions per minute per IP (one was used above)


async def test_http_telegram_login_unavailable_without_bot(http, world):
    r = await http.post(f"{P}/sessions", json={"store_id": str(world.nobot.id)})
    assert r.status_code == 503 and r.json()["error"]["code"] == "TELEGRAM_LOGIN_UNAVAILABLE"
