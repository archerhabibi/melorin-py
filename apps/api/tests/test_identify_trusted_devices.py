"""Automatic identity verification: trust levels (manual -> auto -> silent), revocation and account-binding rules."""

import datetime as dt
import types

import pytest
from sqlalchemy import select

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from _chan import fake_request  # noqa: E402
from melorin.channels.telegram import trust, web
from melorin.core import db, ratelimit
from melorin.core.db import utcnow
from melorin.kernel.models.identity import Identity, RefreshToken, TelegramLoginSession, TrustedDevice, User
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent, FeatureFlag, SecurityEvent, SystemSetting
from melorin.modules.identity.schemas import TelegramProfile

_REQ = fake_request("localhost")
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
KEY = "k" * 43  # a well-formed device key (32-128 url-safe chars)
OTHER_KEY = "z" * 43
HOME = "203.0.113.7"


def _tables():
    from melorin.kernel.models import system

    extra = [getattr(system, n).__table__ for n in ("OutboxEvent", "Notification") if hasattr(system, n)]
    return [
        User.__table__,
        Identity.__table__,
        RefreshToken.__table__,
        Store.__table__,
        TelegramLoginSession.__table__,
        TrustedDevice.__table__,
        AuditEvent.__table__,
        SecurityEvent.__table__,
        FeatureFlag.__table__,
        SystemSetting.__table__,
        *extra,
    ]


def prof(tid=111):
    return TelegramProfile(telegram_id=tid, first_name="Ali")


@pytest.fixture
async def world(tmp_path, monkeypatch):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/trust.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=_tables()))
    monkeypatch.setattr(ratelimit, "get_redis", lambda: None)
    ratelimit._mem.clear()
    async with db.session_factory()() as s:
        main = Store(kind="main", name="Main", slug="main", bot_username="@melorin_bot")
        other = Store(kind="reseller", name="Shop", slug="shop", bot_username="shop_bot")
        s.add_all([main, other])
        await s.commit()
        yield types.SimpleNamespace(s=s, main=main, other=other)
    await db.engine().dispose()


async def _start(w, *, key=KEY, ip=HOME, store=None, remember=True):
    return await web.create_session(w.s, store or w.main, ip=ip, user_agent=CHROME, device_key=key, remember=remember)


async def _manual_login(w, *, key=KEY, ip=HOME, tid=111):
    st = await _start(w, key=key, ip=ip)
    await web.inspect(w.s, st.row.public_id, w.main.id, tid)
    assert (await web.decide(w.s, st.row.public_id, w.main.id, prof(tid), "approve", st.row.match_code)) == {"result": "approved"}
    return st


# ---------------- pure helpers ----------------
def test_network_grouping_is_24_for_ipv4_and_48_for_ipv6():
    assert trust.same_network("203.0.113.7", "203.0.113.200")
    assert not trust.same_network("203.0.113.7", "203.0.114.7")
    assert trust.same_network("2001:db8:1:1::1", "2001:db8:1:1:ffff::2")
    assert not trust.same_network("2001:db8:1::1", "2001:db8:2::1")
    assert not trust.same_network(None, "203.0.113.7") and not trust.same_network("garbage", "garbage")


def test_device_key_must_be_well_formed_and_is_hashed():
    assert trust.key_hash_of(KEY) and trust.key_hash_of(KEY) != KEY and len(trust.key_hash_of(KEY)) == 64
    for bad in (None, "", "short", "has space " * 5, "x" * 200, "!" * 40):
        assert trust.key_hash_of(bad) is None


# ---------------- levels ----------------
async def test_unknown_browser_is_manual_and_a_manual_approval_earns_trust(world):
    st = await _start(world)
    assert st.level == "manual" and st.row.auto_level is None
    await _manual_login(world)
    dev = await world.s.scalar(select(TrustedDevice))
    assert dev is not None and dev.key_hash == trust.key_hash_of(KEY) and dev.key_hash != KEY  # only the hash is stored
    assert dev.last_ip == HOME and dev.store_id == world.main.id and dev.revoked_at is None


async def test_known_browser_on_new_network_is_auto_and_needs_no_number(world):
    await _manual_login(world)
    st = await _start(world, ip="198.51.100.9")
    assert st.level == "auto" and st.row.status == "pending" and st.row.auto_level == "auto"
    info = await web.inspect(world.s, st.row.public_id, world.main.id, 111, profile=prof())
    assert info.status == "approved"  # opening the bot link was the whole approval
    res = await web.poll(world.s, st.row.public_id, st.poll_token, _REQ)
    assert res.status == "approved" and res.tokens is not None


async def test_known_browser_on_same_network_is_silent_with_no_bot_step(world):
    await _manual_login(world)
    st = await _start(world, ip="203.0.113.99")  # same /24
    assert st.level == "silent" and st.row.status == "approved"
    res = await web.poll(world.s, st.row.public_id, st.poll_token, _REQ)
    assert res.status == "approved" and res.tokens is not None
    assert (await web.poll(world.s, st.row.public_id, st.poll_token, _REQ)).status == "consumed"  # still single use


async def test_silent_window_expires_into_auto(world):
    await _manual_login(world)
    dev = await world.s.scalar(select(TrustedDevice))
    dev.last_seen_at = utcnow() - dt.timedelta(days=trust.silent_days() + 1)
    await world.s.commit()
    assert (await _start(world)).level == "auto"


async def test_expired_trust_falls_back_to_manual(world):
    await _manual_login(world)
    dev = await world.s.scalar(select(TrustedDevice))
    dev.expires_at = utcnow() - dt.timedelta(seconds=1)
    await world.s.commit()
    assert (await _start(world)).level == "manual"


async def test_remember_false_does_not_create_trust(world):
    st = await _start(world, remember=False)
    await web.inspect(world.s, st.row.public_id, world.main.id, 111)
    await web.decide(world.s, st.row.public_id, world.main.id, prof(), "approve", st.row.match_code)
    assert (await world.s.scalar(select(TrustedDevice))) is None


# ---------------- anti-phishing / isolation ----------------
async def test_attacker_browser_with_a_relayed_link_never_gets_automatic_trust(world):
    await _manual_login(world)
    st = await _start(world, key=OTHER_KEY, ip="198.51.100.66")  # a different browser: no key the victim ever approved
    assert st.level == "manual" and st.row.match_code  # the number match still stands between them and the account


async def test_trust_is_per_store(world):
    await _manual_login(world)
    assert (await _start(world, store=world.other)).level == "manual"


async def test_key_approved_for_one_account_cannot_be_rebound_to_another(world):
    await _manual_login(world, tid=111)
    st = await _start(world, ip="198.51.100.9")  # auto attempt on the first account's browser...
    info = await web.inspect(world.s, st.row.public_id, world.main.id, 222, profile=prof(222))  # ...opened by someone else
    assert info.status != "approved"
    assert (await world.s.scalar(select(TrustedDevice))).telegram_id == 111


# ---------------- revocation ----------------
async def test_not_me_revokes_all_devices_and_web_sessions(world):
    await _manual_login(world)
    st = await _start(world, ip="203.0.113.50")
    await web.poll(world.s, st.row.public_id, st.poll_token, _REQ)  # silent login issued a refresh token
    assert await web.revoke_devices(world.s, world.main.id, 111, None) == 1
    dev = await world.s.scalar(select(TrustedDevice).execution_options(populate_existing=True))
    assert dev.revoked_at is not None
    assert all(t.revoked_at is not None for t in (await world.s.scalars(select(RefreshToken))).all())
    assert (await _start(world)).level == "manual"
    assert "tg_web_login_devices_revoked" in (await world.s.scalars(select(SecurityEvent.kind))).all()


async def test_a_telegram_account_can_only_revoke_its_own_devices(world):
    await _manual_login(world, tid=111)
    dev = await world.s.scalar(select(TrustedDevice))
    assert await web.revoke_devices(world.s, world.main.id, 222, dev.id.hex) == 0
    assert await web.revoke_devices(world.s, world.main.id, 111, "not-a-uuid") == 0
    assert len(await web.list_devices(world.s, world.main.id, 111)) == 1


async def test_browser_can_forget_itself_by_holding_the_key(world):
    await _manual_login(world)
    assert await web.forget_device(world.s, "short") == 0
    assert await web.forget_device(world.s, OTHER_KEY) == 0
    assert await web.forget_device(world.s, KEY) == 1
    assert (await _start(world)).level == "manual"


async def test_device_list_is_capped_and_oldest_make_room(world):
    for i in range(trust.MAX_DEVICES_PER_ACCOUNT + 2):
        ratelimit._mem.clear()  # the hourly approval limiter is not what this test is about
        await _manual_login(world, key=f"{i:02d}".ljust(40, "a"))
    live = await web.list_devices(world.s, world.main.id, 111)
    assert len(live) == trust.MAX_DEVICES_PER_ACCOUNT


# ---------------- housekeeping ----------------
async def test_purge_removes_long_dead_devices_but_keeps_recent_ones(world):
    await _manual_login(world, key="a" * 40)
    await _manual_login(world, key="b" * 40)
    old, fresh = (await world.s.scalars(select(TrustedDevice).order_by(TrustedDevice.created_at))).all()
    old.revoked_at = utcnow() - dt.timedelta(days=45)
    fresh.revoked_at = utcnow() - dt.timedelta(days=2)
    await world.s.commit()
    await web.purge_old(world.s)
    left = (await world.s.scalars(select(TrustedDevice))).all()
    assert [d.key_hash for d in left] == [fresh.key_hash]


# ---------------- HTTP: the device key is an HttpOnly cookie, never page-readable ----------------
@pytest.fixture
async def http(world):
    import httpx
    from fastapi import FastAPI

    from melorin.channels.telegram.web_router import tgweb
    from melorin.core.deps import get_session
    from melorin.core.errors import install

    app = FastAPI()
    install(app)
    app.include_router(tgweb, prefix="/api/v1")

    async def override():
        async with db.session_factory()() as s:
            yield s

    app.dependency_overrides[get_session] = override
    transport = httpx.ASGITransport(app=app, client=(HOME, 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"user-agent": CHROME}) as c:
        yield c


P = "/api/v1/auth/telegram/web"


async def test_http_start_mints_an_httponly_device_cookie_and_trust_follows_it(http, world):
    r = await http.post(f"{P}/sessions", json={"store_id": str(world.main.id)})
    assert r.status_code == 200 and r.json()["level"] == "manual"
    cookie = r.headers["set-cookie"].lower()
    assert "melorin_dk=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and f"path={P}" in cookie
    key = http.cookies.get("melorin_dk")
    assert trust.key_hash_of(key)
    s = r.json()
    await web.inspect(world.s, s["session_id"], world.main.id, 111)
    row = await world.s.scalar(select(TelegramLoginSession).where(TelegramLoginSession.public_id == s["session_id"]))
    await web.decide(world.s, s["session_id"], world.main.id, prof(), "approve", row.match_code)
    again = (await http.post(f"{P}/sessions", json={"store_id": str(world.main.id)})).json()
    assert again["level"] == "silent" and again["match_code"] is None  # same cookie, same network: no bot step at all
    got = await http.post(f"{P}/sessions/{again['session_id']}/poll", json={"poll_token": again["poll_token"]})
    assert got.json()["status"] == "approved" and got.json()["tokens"]


async def test_http_forget_drops_trust_and_the_cookie(http, world):
    s = (await http.post(f"{P}/sessions", json={"store_id": str(world.main.id)})).json()
    await web.inspect(world.s, s["session_id"], world.main.id, 111)
    row = await world.s.scalar(select(TelegramLoginSession).where(TelegramLoginSession.public_id == s["session_id"]))
    await web.decide(world.s, s["session_id"], world.main.id, prof(), "approve", row.match_code)
    r = await http.post(f"{P}/devices/forget", json={})
    assert r.status_code == 200 and r.json() == {"revoked": 1}
    assert "melorin_dk=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()
    assert (await world.s.scalar(select(TrustedDevice).execution_options(populate_existing=True))).revoked_at is not None


async def test_http_forget_without_any_key_is_a_harmless_noop(http):
    r = await http.post(f"{P}/devices/forget", json={})
    assert r.status_code == 200 and r.json() == {"revoked": 0}
