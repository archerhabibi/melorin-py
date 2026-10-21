"""Admin management of reseller stores + the Core side of the reseller bot runtime (SQLite, Telegram mocked)."""

import datetime as dt
import types
import uuid

import pytest

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.admin import resellers as r
from melorin.modules.identity.models import User
from melorin.modules.reseller import bots, identity
from melorin.modules.stores.models import BotStoreBinding, ResellerProfile, Store
from melorin.modules.system.models import AuditEvent

ADMIN = types.SimpleNamespace(id=uuid.uuid4())
TOKEN = "123456789:" + "A" * 35
OTHER = "987654321:" + "B" * 35


@pytest.fixture
async def session(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "encrypt", lambda raw: f"enc:{raw}")
    monkeypatch.setattr(r, "decrypt", lambda raw: raw.removeprefix("enc:"))
    monkeypatch.setattr(bots, "decrypt", lambda raw: raw.removeprefix("enc:"))
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/resellers.db")
    seen = set()  # BotStoreBinding declares one index twice (Index + index=True); SQLite refuses the duplicate
    for idx in list(BotStoreBinding.__table__.indexes):
        if idx.name in seen:
            BotStoreBinding.__table__.indexes.discard(idx)
        seen.add(idx.name)
    async with db.engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    async with db.session_factory()() as s:
        yield s
    await db.engine().dispose()


async def make_store(session, slug="shop", *, domain="shop.example.com", token=TOKEN, **over):
    owner = User(email=f"{slug}@example.com", display_name=f"Owner {slug}")
    session.add(owner)
    await session.flush()
    st = Store(
        kind="reseller",
        name=f"Store {slug}",
        slug=slug,
        owner_user_id=owner.id,
        domain=domain,
        currency="IRT",
        bot_token_enc=f"enc:{token}" if token else None,
        bot_username=f"{slug}_bot" if token else None,
        **over,
    )
    session.add(st)
    await session.flush()
    session.add(ResellerProfile(store_id=st.id, user_id=owner.id, debt_limit=100, api_enabled=True, sales_enabled=True))
    if token:
        session.add(
            BotStoreBinding(
                bot_key="tg:" + token.split(":")[0],
                bot_username=f"{slug}_bot",
                store_id=st.id,
                owner_user_id=owner.id,
                bot_kind="reseller",
                status="active",
            )
        )
    await session.commit()
    return st


async def test_admin_can_edit_identity_standing_and_limits_and_it_is_audited(session):
    st = await make_store(session)
    out = await r.edit_reseller(
        st.id,
        r.ResellerEdit(
            name="New Name",
            domain=" https://NEW.Example.com/x ",
            debt_limit=5000,
            sales_enabled=False,
            api_enabled=False,
            status="suspended",
        ),
        ADMIN,
        session,
    )
    assert out["name"] == "New Name" and out["domain"] == "new.example.com" and out["status"] == "suspended"
    assert out["debt_limit"] == 5000 and out["sales_enabled"] is False and out["api_enabled"] is False
    from sqlalchemy import select

    ev = (await session.scalars(select(AuditEvent).where(AuditEvent.action == "reseller.edited"))).one()
    assert ev.data["before"]["debt_limit"] == 100 and ev.data["after"]["debt_limit"] == 5000


async def test_edit_with_nothing_changed_writes_no_audit_event(session):
    st = await make_store(session)
    await r.edit_reseller(st.id, r.ResellerEdit(name=st.name, debt_limit=100), ADMIN, session)
    from sqlalchemy import select

    assert (await session.scalars(select(AuditEvent))).all() == []


async def test_domain_must_be_valid_unique_and_not_a_platform_host(session):
    a, b = (
        await make_store(session, "a", domain="a.example.com", token=None),
        await make_store(session, "b", domain="b.example.com", token=None),
    )
    with pytest.raises(AppError) as e:
        await r.edit_reseller(b.id, r.ResellerEdit(domain="a.example.com"), ADMIN, session)
    assert e.value.code == "DOMAIN_TAKEN"
    with pytest.raises(AppError) as e:
        await r.edit_reseller(b.id, r.ResellerEdit(domain="10.0.0.1"), ADMIN, session)
    assert e.value.code == "INVALID_DOMAIN"
    await r.edit_reseller(a.id, r.ResellerEdit(domain="a.example.com"), ADMIN, session)  # re-saving its own domain is fine


async def test_only_reseller_stores_can_be_edited(session):
    main = Store(kind="main", name="Main", slug="main", currency="IRT")
    session.add(main)
    await session.commit()
    with pytest.raises(AppError):
        await r.edit_reseller(main.id, r.ResellerEdit(name="Hacked"), ADMIN, session)


async def test_bot_texts_are_validated_and_blank_ones_removed(session):
    st = await make_store(session)
    out = await r.edit_reseller(st.id, r.ResellerEdit(bot_messages={"welcome": " سلام ", "support": "  "}), ADMIN, session)
    assert out["bot_messages"] == {"welcome": "سلام"}
    with pytest.raises(AppError) as e:
        await r.edit_reseller(st.id, r.ResellerEdit(bot_messages={"evil": "x"}), ADMIN, session)
    assert e.value.code == "INVALID_BOT_TEXT"
    with pytest.raises(AppError) as e:
        await r.edit_reseller(st.id, r.ResellerEdit(bot_messages={"welcome": "x" * 1001}), ADMIN, session)
    assert e.value.code == "BOT_TEXT_TOO_LONG"


async def test_set_bot_token_verifies_with_telegram_stores_encrypted_and_rebinds(session, monkeypatch):
    st = await make_store(session, token=None)

    async def fake_verify(token, **kw):
        return "newbot"

    monkeypatch.setattr(identity, "verify_bot", fake_verify)
    out = await r.set_bot_token(st.id, r.BotTokenIn(token=f" {TOKEN} "), ADMIN, session)
    assert out["bot"]["has_token"] and out["bot"]["username"] == "newbot" and out["bot"]["state"] == "pending"
    assert "enc:" not in str(out) and TOKEN not in str(out)  # the token is never returned
    await session.refresh(st)
    assert st.bot_token_enc == f"enc:{TOKEN}"
    from sqlalchemy import select

    binding = (await session.scalars(select(BotStoreBinding).where(BotStoreBinding.store_id == st.id))).one()
    assert binding.bot_key == "tg:123456789" and binding.bot_username == "newbot"


async def test_set_bot_token_rejects_bad_format_unreachable_telegram_and_a_bot_used_elsewhere(session, monkeypatch):
    a, b = await make_store(session, "a", domain="a.example.com"), await make_store(session, "b", domain="b.example.com", token=None)

    async def reachable(token, **kw):
        return "bbot"

    async def unreachable(token, **kw):
        return None

    with pytest.raises(AppError) as e:
        await r.set_bot_token(b.id, r.BotTokenIn(token="not-a-token-at-all"), ADMIN, session)
    assert e.value.code == "INVALID_BOT_TOKEN"
    monkeypatch.setattr(identity, "verify_bot", unreachable)
    with pytest.raises(AppError) as e:
        await r.set_bot_token(b.id, r.BotTokenIn(token=OTHER), ADMIN, session)
    assert e.value.code == "TELEGRAM_UNREACHABLE"
    monkeypatch.setattr(identity, "verify_bot", reachable)
    with pytest.raises(AppError) as e:
        await r.set_bot_token(b.id, r.BotTokenIn(token=TOKEN), ADMIN, session)  # bot of store "a"
    assert e.value.code == "BOT_TAKEN"
    await r.set_bot_token(a.id, r.BotTokenIn(token=TOKEN), ADMIN, session)  # re-saving a store's own bot is fine


async def test_clearing_the_token_frees_the_bot_and_stops_it(session):
    st = await make_store(session)
    out = await r.clear_bot_token(st.id, ADMIN, session)
    assert out["bot"]["state"] == "no_token" and out["bot"]["username"] is None
    from sqlalchemy import select

    assert (await session.scalars(select(BotStoreBinding))).all() == []
    assert await bots.runnable_bots(session) == []


async def test_verify_bot_marks_error_when_telegram_rejects_the_stored_token(session, monkeypatch):
    st = await make_store(session)

    async def rejected(token, **kw):
        raise AppError("BOT_TOKEN_REJECTED", "no", 422)

    monkeypatch.setattr(identity, "verify_bot", rejected)
    with pytest.raises(AppError):
        await r.verify_store_bot(st.id, ADMIN, session)
    await session.refresh(st)
    assert st.bot_status == "error" and "توکن" in st.bot_status_detail


async def test_runnable_bots_are_only_active_enabled_stores_with_a_token(session):
    ok = await make_store(session, "ok", domain="ok.example.com", token=TOKEN)
    await make_store(session, "off", domain="off.example.com", token=OTHER, bot_enabled=False)
    await make_store(session, "sus", domain="sus.example.com", token="111111111:" + "C" * 35, status="suspended")
    await make_store(session, "none", domain="none.example.com", token=None)
    got = await bots.runnable_bots(session)
    assert [b["slug"] for b in got] == ["ok"] and got[0]["token"] == TOKEN and got[0]["store_id"] == ok.id
    assert len(got[0]["fingerprint"]) == 16 and TOKEN not in got[0]["fingerprint"]


async def test_fingerprint_changes_with_the_token_so_the_runner_restarts(session):
    st = await make_store(session)
    assert bots.fingerprint(st, TOKEN) != bots.fingerprint(st, OTHER)


async def test_status_reports_are_stored_and_stale_or_foreign_reports_are_ignored(session):
    st = await make_store(session)
    fp = bots.fingerprint(st, TOKEN)
    assert await bots.apply_status(session, st.id, bots.BotStatusIn(state="running", fingerprint=fp)) is True
    await session.refresh(st)
    assert bots.effective_state(st) == "running"
    # a runner still holding an OLD token must not overwrite the state of the new one
    assert await bots.apply_status(session, st.id, bots.BotStatusIn(state="error", detail="old", fingerprint="deadbeefdeadbeef")) is False
    await session.refresh(st)
    assert st.bot_status == "running"
    with pytest.raises(AppError):
        await bots.apply_status(session, st.id, bots.BotStatusIn(state="hacked"))


async def test_a_running_bot_that_stopped_reporting_is_shown_offline(session):
    st = await make_store(session)
    st.bot_status, st.bot_seen_at = "running", dt.datetime.now(dt.UTC) - bots.STALE_AFTER - dt.timedelta(seconds=5)
    assert bots.effective_state(st) == "offline"
    st.bot_seen_at = dt.datetime.now(dt.UTC)
    assert bots.effective_state(st) == "running"
    st.bot_enabled = False
    assert bots.effective_state(st) == "disabled"
    st.bot_enabled, st.status = True, "suspended"
    assert bots.effective_state(st) == "store_suspended"


async def test_admin_list_shows_owner_bot_state_and_never_the_token(session):
    await make_store(session)
    rows = await r.list_resellers(ADMIN, session)
    assert rows[0]["owner"]["email"] == "shop@example.com" and rows[0]["bot"]["has_token"] is True
    assert TOKEN not in str(rows) and "enc:" not in str(rows)


def test_internal_routes_refuse_anything_that_came_through_a_reverse_proxy():
    def req(**headers):
        return types.SimpleNamespace(headers={k.lower(): v for k, v in headers.items()})

    bots._internal_only(req())  # direct call on the private network
    for h in ("X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP"):
        with pytest.raises(AppError):
            bots._internal_only(req(**{h: "1.2.3.4"}))


def test_internal_router_requires_the_bot_secret_and_is_hidden_from_the_docs():
    deps = [d.dependency.__name__ for d in bots.internal.dependencies]
    assert "_reseller_runner_only" in deps and "_internal_only" in deps  # the former wraps require_bot_service (secret check)
    assert "require_bot_service" in __import__("inspect").getsource(bots)
    assert bots.internal.include_in_schema is False


def test_admin_ui_has_a_resellers_screen_and_never_asks_core_for_the_token():
    from pathlib import Path

    web = Path(__file__).parents[2] / "admin-web/src"
    assert '"نمایندگان": ResellersView' in (web / "AdminExtra.jsx").read_text()
    assert "'resellers'" in (web / "App.jsx").read_text()
    view = (web / "ResellersView.jsx").read_text()
    assert "/api/v1/admin/resellers" in view and "/bot-token" in view and "/verify-bot" in view
    assert "bot_token" not in view  # the token is write-only: the screen only ever sends it
