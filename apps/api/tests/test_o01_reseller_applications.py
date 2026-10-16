"""Reseller applications: store domain + reseller bot token, admin review, uniqueness and secrecy of the token."""
import importlib.util
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import melorin.models  # noqa: F401
from melorin.core.crypto import decrypt
from melorin.core.db import Base
from melorin.core.errors import AppError
from melorin.modules.admin.router import applications, review_application, verify_application_bot
from melorin.modules.admin.schemas import ResellerApproval
from melorin.modules.identity.models import User
from melorin.modules.reseller import identity
from melorin.modules.reseller.router import apply, cancel_application, my_applications
from melorin.modules.reseller.schemas import ApplicationIn
from melorin.modules.stores.models import BotStoreBinding, ResellerApplication, ResellerProfile, Store, StoreMembership
from melorin.modules.system.models import OutboxEvent

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:" + "A" * 35
TOKEN2 = "987654321:" + "B" * 35
REAL_VERIFY = identity.verify_bot  # the autouse fixture below replaces the module attribute


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.sorted_tables:  # one by one: a pre-existing duplicate index breaks create_all on SQLite
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
        except Exception:
            pass
    # SQLite ignores postgresql_where, so these partial-unique indexes become full-unique there and would
    # block re-using a domain/bot after a cancel or reject. Application code enforces "pending only" itself.
    async with engine.begin() as conn:
        for ix in ("uq_reseller_application_pending_domain", "uq_reseller_application_pending_bot", "uq_reseller_application_pending_user_store"):
            await conn.exec_driver_sql(f"DROP INDEX IF EXISTS {ix}")
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def no_telegram(monkeypatch):
    async def fake(token, **_):
        return "shopbot"

    monkeypatch.setattr(identity, "verify_bot", fake)


async def world(s, n=1):
    main = Store(kind="main", name="Main", slug="main", currency="IRT")
    admin = User(email="admin@x.io", is_super_admin=True)
    s.add_all([main, admin])
    users = [User(email=f"u{i}@x.io", display_name=f"U{i}") for i in range(n)]
    s.add_all(users)
    await s.flush()
    s.add_all([StoreMembership(store_id=main.id, user_id=u.id, role="customer") for u in users])
    await s.commit()
    return main, admin, users


def body(main, **kw):
    d = dict(store_name="Shop One", target_store_id=main.id, domain="Shop.Example.com", bot_token=TOKEN)
    return ApplicationIn(**{**d, **kw})


async def code_of(coro):
    with pytest.raises(AppError) as e:
        await coro
    return e.value.code


def test_normalize_domain():
    assert identity.normalize_domain("  https://Shop.Example.com/path?x=1 ") == "shop.example.com"
    assert identity.normalize_domain("sub.shop.ir.") == "sub.shop.ir"
    for bad in ["localhost", "shop", "10.0.0.1", "shop.example.com:8080", "a_b.com", "-x.com", "shop.local", "x@shop.com", "shop.123"]:
        with pytest.raises(AppError) as e:
            identity.normalize_domain(bad)
        assert e.value.code == "INVALID_DOMAIN", bad


def test_platform_hosts_are_reserved(monkeypatch):
    monkeypatch.setattr(identity, "platform_hosts", lambda: {"app.melorin.ir"})
    with pytest.raises(AppError) as e:
        identity.normalize_domain("https://APP.melorin.ir/")
    assert e.value.code == "DOMAIN_RESERVED"
    assert identity.normalize_domain("shop.melorin.ir") == "shop.melorin.ir"


def test_parse_bot_token_never_leaks_secret_into_key():
    token, key = identity.parse_bot_token(f"  {TOKEN} ")
    assert token == TOKEN and key == "tg:123456789" and "AAAA" not in key
    for bad in ["", "abc", "123:short", "x" * 40, "123456789:" + "A" * 10]:
        with pytest.raises(AppError) as e:
            identity.parse_bot_token(bad)
        assert e.value.code == "INVALID_BOT_TOKEN"


async def test_verify_bot_outcomes():
    def t(status, payload=None):
        return httpx.MockTransport(lambda req: httpx.Response(status, json=payload or {}))

    assert await REAL_VERIFY(TOKEN, transport=t(200, {"ok": True, "result": {"is_bot": True, "username": "shopbot"}})) == "shopbot"
    with pytest.raises(AppError) as e:
        await REAL_VERIFY(TOKEN, transport=t(401))
    assert e.value.code == "BOT_TOKEN_REJECTED"

    def boom(req):
        raise httpx.ConnectError("down")

    assert await REAL_VERIFY(TOKEN, transport=httpx.MockTransport(boom)) is None  # unreachable Telegram does not block


async def test_apply_stores_encrypted_token_and_never_returns_it(session):
    main, _, (u,) = await world(session)
    out = await apply(body(main), u, session)
    assert out["domain"] == "shop.example.com" and out["bot_username"] == "shopbot" and out["bot_verified"] is True
    assert TOKEN not in str(out) and "bot_token" not in out and "bot_token_enc" not in out
    row = await session.get(ResellerApplication, out["id"])
    assert row.bot_token_enc and row.bot_token_enc != TOKEN and decrypt(row.bot_token_enc) == TOKEN and row.bot_key == "tg:123456789"
    mine = await my_applications(u, session)
    assert len(mine) == 1 and TOKEN not in str(mine)


async def test_apply_requires_valid_identifiers_and_membership(session):
    main, _, (u,) = await world(session)
    assert await code_of(apply(body(main, domain="not a domain"), u, session)) == "INVALID_DOMAIN"
    assert await code_of(apply(body(main, bot_token="x" * 30), u, session)) == "INVALID_BOT_TOKEN"
    outsider = User(email="o@x.io")
    session.add(outsider)
    await session.commit()
    assert await code_of(apply(body(main), outsider, session)) == "STORE_MEMBERSHIP_REQUIRED"


async def test_duplicate_domain_or_bot_is_rejected_across_applicants(session):
    main, _, (u1, u2) = await world(session, 2)
    await apply(body(main), u1, session)
    assert await code_of(apply(body(main, bot_token=TOKEN2), u2, session)) == "DOMAIN_TAKEN"
    assert await code_of(apply(body(main, domain="other.example.com"), u2, session)) == "BOT_TAKEN"
    await apply(body(main, domain="other.example.com", bot_token=TOKEN2), u2, session)


async def test_one_pending_application_per_user_and_store(session):
    main, _, (u,) = await world(session)
    await apply(body(main), u, session)
    assert await code_of(apply(body(main, domain="b.example.com", bot_token=TOKEN2), u, session)) == "APPLICATION_EXISTS"


async def test_cancel_frees_identifiers_and_drops_token(session):
    main, _, (u1, u2) = await world(session, 2)
    a = await apply(body(main), u1, session)
    with pytest.raises(AppError):
        await cancel_application(a["id"], u2, session)  # not the owner
    out = await cancel_application(a["id"], u1, session)
    assert out["status"] == "cancelled"
    assert (await session.get(ResellerApplication, a["id"])).bot_token_enc is None
    await apply(body(main), u2, session)  # same domain/bot usable again
    assert await code_of(cancel_application(a["id"], u1, session)) == "APPLICATION_NOT_PENDING"


async def test_approval_builds_store_profile_binding_and_moves_token(session):
    main, admin, (u,) = await world(session)
    a = await apply(body(main), u, session)
    res = await review_application(a["id"], ResellerApproval(approve=True, debt_limit=500000), admin, session)
    st = await session.get(Store, res["store_id"])
    assert st.kind == "reseller" and st.parent_store_id == main.id and st.owner_user_id == u.id
    assert st.domain == "shop.example.com" and st.bot_username == "shopbot" and decrypt(st.bot_token_enc) == TOKEN
    prof = await session.scalar(select(ResellerProfile).where(ResellerProfile.store_id == st.id))
    assert prof.debt_limit == 500000 and prof.api_enabled is True
    member = await session.scalar(select(StoreMembership).where(StoreMembership.store_id == st.id, StoreMembership.user_id == u.id))
    assert member.role == "owner"
    bind = await session.scalar(select(BotStoreBinding).where(BotStoreBinding.store_id == st.id))
    assert bind.bot_key == "tg:123456789" and bind.bot_kind == "reseller" and bind.owner_user_id == u.id
    assert (await session.get(ResellerApplication, a["id"])).bot_token_enc is None
    ev = (await session.scalars(select(OutboxEvent))).all()
    assert any(e.payload.get("kind") == "reseller_application" and "تأیید" in e.payload["title"] for e in ev)
    assert await code_of(review_application(a["id"], ResellerApproval(approve=True), admin, session)) == "NOT_FOUND"  # no double review


async def test_rejection_needs_reason_shows_it_to_applicant_and_frees_identifiers(session):
    main, admin, (u1, u2) = await world(session, 2)
    a = await apply(body(main), u1, session)
    assert await code_of(review_application(a["id"], ResellerApproval(approve=False), admin, session)) == "REASON_REQUIRED"
    await review_application(a["id"], ResellerApproval(approve=False, reason="دامنه تأیید نشد"), admin, session)
    mine = await my_applications(u1, session)
    assert mine[0]["status"] == "rejected" and mine[0]["review_reason"] == "دامنه تأیید نشد"
    assert not await session.scalar(select(Store.id).where(Store.kind == "reseller"))
    await apply(body(main), u2, session)


async def test_approval_rechecks_uniqueness_and_legacy_applications(session):
    main, admin, (u,) = await world(session)
    legacy = ResellerApplication(user_id=u.id, target_store_id=main.id, store_name="Old")
    session.add(legacy)
    await session.commit()
    assert await code_of(review_application(legacy.id, ResellerApproval(approve=True), admin, session)) == "APPLICATION_INCOMPLETE"
    await review_application(legacy.id, ResellerApproval(approve=False, reason="لطفاً دوباره با دامنه و ربات ثبت کنید"), admin, session)
    a = await apply(body(main), u, session)
    # the domain gets taken by a store created some other way after the application was filed
    session.add(Store(kind="reseller", name="Squatter", slug="sq", domain="shop.example.com", parent_store_id=main.id))
    await session.commit()
    assert await code_of(review_application(a["id"], ResellerApproval(approve=True), admin, session)) == "DOMAIN_TAKEN"


async def test_admin_list_is_enriched_pending_first_and_has_no_token(session):
    main, admin, (u1, u2) = await world(session, 2)
    a1 = await apply(body(main), u1, session)
    await review_application(a1["id"], ResellerApproval(approve=False, reason="no"), admin, session)
    await apply(body(main, domain="two.example.com", bot_token=TOKEN2), u2, session)
    rows = await applications(admin, session)
    assert [r["status"] for r in rows] == ["pending", "rejected"]
    assert rows[0]["user_email"] == "u1@x.io" and rows[0]["target_store_name"] == "Main" and rows[0]["domain"] == "two.example.com" and rows[0]["has_bot_token"] is True
    assert TOKEN not in str(rows) and TOKEN2 not in str(rows) and "bot_token_enc" not in rows[0]
    assert [r["status"] for r in await applications(admin, session, status="rejected")] == ["rejected"]


def test_migration_0017_chains_from_0016_and_fits_version_column():
    spec = importlib.util.spec_from_file_location("m0017", ROOT / "alembic/versions/0017_reseller_domain_bot.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.down_revision == "0016_sales_pools" and len(m.revision) <= 32


def test_rotation_covers_application_token():
    assert "(ResellerApplication, \"bot_token_enc\")" in (ROOT / "melorin/cli.py").read_text()


async def test_admin_can_reverify_bot_when_first_check_could_not_reach_telegram(session, monkeypatch):
    main, admin, (u,) = await world(session)

    async def unreachable(token, **_):
        return None

    monkeypatch.setattr(identity, "verify_bot", unreachable)
    a = await apply(body(main), u, session)
    assert a["bot_verified"] is False and a["bot_username"] is None
    assert await code_of(verify_application_bot(a["id"], admin, session)) == "TELEGRAM_UNREACHABLE"

    async def reachable(token, **_):
        assert token == TOKEN  # the stored token is decrypted for the check, never returned
        return "shopbot"

    monkeypatch.setattr(identity, "verify_bot", reachable)
    row = await verify_application_bot(a["id"], admin, session)
    assert row["bot_verified"] is True and row["bot_username"] == "shopbot" and TOKEN not in str(row)
