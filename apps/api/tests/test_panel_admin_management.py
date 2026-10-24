import types
import uuid

import pytest

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.admin import router as r
from melorin.modules.admin.schemas import CreatePanel, PanelState
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import Panel

ADMIN = types.SimpleNamespace(id=uuid.uuid4())


@pytest.fixture
async def session(tmp_path, monkeypatch):
    monkeypatch.setattr("melorin.modules.admin.panels.encrypt", lambda raw: f"enc:{raw}")
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/panels.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[Panel.__table__, AuditEvent.__table__]))
    async with db.session_factory()() as s:
        yield s
    await db.engine().dispose()


def _sanaei(**over):
    body = dict(
        name="DE-1",
        kind="sanaei",
        base_url="https://p.example.com:2053/x",
        credentials={"api_token": "t0k"},
        config={"inbound_ids": [1], "sub_base_url": "https://sub.example.com:2096/sub"},
    )
    body.update(over)
    return CreatePanel(**body)


async def test_pasarguard_create_requires_credentials_but_edit_may_omit_them(session):
    cfg = {"group_ids": [1]}
    with pytest.raises(AppError):
        await r.create_panel(CreatePanel(name="PG", kind="pasarguard", base_url="https://pg.example.com", config=cfg), ADMIN, session)
    out = await r.create_panel(
        CreatePanel(name="PG", kind="pasarguard", base_url="https://pg.example.com", credentials={"api_key": "k"}, config=cfg),
        ADMIN,
        session,
    )
    assert out.has_credentials is True and out.config == cfg
    # editing without re-sending the secret must validate and keep the stored one
    await r.update_panel(out.id, CreatePanel(name="PG2", kind="pasarguard", base_url="https://pg.example.com", config=cfg), ADMIN, session)
    p = await session.get(Panel, out.id)
    assert p.name == "PG2" and p.credentials_enc == 'enc:{"api_key": "k"}'


async def test_edit_replaces_secret_only_when_supplied_and_resets_health_on_connection_change(session):
    out = await r.create_panel(_sanaei(), ADMIN, session)
    p = await session.get(Panel, out.id)
    p.health_status, p.last_health_error = "healthy", None
    await session.commit()

    await r.update_panel(out.id, _sanaei(name="Renamed", credentials={}), ADMIN, session)  # name only
    await session.refresh(p)
    assert p.name == "Renamed" and p.health_status == "healthy" and "t0k" in p.credentials_enc

    await r.update_panel(out.id, _sanaei(name="Renamed", credentials={}, base_url="https://q.example.com"), ADMIN, session)
    await session.refresh(p)
    assert p.health_status == "unknown" and p.last_health_at is None and "t0k" in p.credentials_enc

    await r.update_panel(out.id, _sanaei(credentials={"api_token": "new"}), ADMIN, session)
    await session.refresh(p)
    assert "new" in p.credentials_enc and "t0k" not in p.credentials_enc


async def test_enable_disable_is_idempotent_and_listed(session):
    out = await r.create_panel(_sanaei(), ADMIN, session)
    assert (await r.set_panel_state(out.id, PanelState(is_enabled=False), ADMIN, session))["is_enabled"] is False
    assert (await r.set_panel_state(out.id, PanelState(is_enabled=False), ADMIN, session))["is_enabled"] is False
    listed = await r.panels(ADMIN, session)
    assert [x.is_enabled for x in listed] == [False] and listed[0].has_credentials is True
    assert (await r.set_panel_state(out.id, PanelState(is_enabled=True), ADMIN, session))["is_enabled"] is True


def test_panel_out_never_exposes_secrets():
    from melorin.modules.admin.schemas import PanelOut

    assert "credentials" not in PanelOut.model_fields and "credentials_enc" not in PanelOut.model_fields


def _upstream(**over):
    body = dict(
        name="Parent",
        kind="upstream_bot",
        base_url="https://t.me/parent_bot",
        credentials={"api_id": 123456, "api_hash": "h", "session": "s"},
        config={"max_price": 100000},
    )
    body.update(over)
    return CreatePanel(**body)


async def test_upstream_bot_create_needs_credentials_but_edit_may_omit_them(session):
    with pytest.raises(AppError):
        await r.create_panel(_upstream(credentials={}), ADMIN, session)
    out = await r.create_panel(_upstream(), ADMIN, session)
    assert out.has_credentials is True and out.config == {"max_price": 100000}
    # the admin form edits settings without re-sending the Telethon session: the stored secret must survive
    await r.update_panel(out.id, _upstream(credentials={}, config={"max_price": 90000, "renew": {"enabled": False}}), ADMIN, session)
    p = await session.get(Panel, out.id)
    assert p.config == {"max_price": 90000, "renew": {"enabled": False}} and '"session": "s"' in p.credentials_enc


@pytest.mark.parametrize(
    "over",
    [
        {"config": {}},
        {"config": {"max_price": "abc"}},
        {"config": {"max_price": 1000, "plans": "10gb"}},
        {"config": {"max_price": 1000, "renew": []}},
        {"config": {"max_price": 1000, "status_ttl": 0}},
        {"config": {"max_price": 1000, "status_ttl": float("nan")}},
        {"config": {"max_price": 1000, "plans": [{"traffic_gb": "abc", "months": 1}]}},
        {"config": {"max_price": 1000, "plans": [{"traffic_gb": 10, "months": 0}]}},
        {"config": {"max_price": 1000, "plans": [{"months": 1}]}},
        {"credentials": {"api_id": "x", "api_hash": "h", "session": "s"}},
        {"credentials": {"api_id": 1, "api_hash": "h"}},
    ],
)
def test_upstream_bot_schema_rejects_unsafe_settings(over):
    with pytest.raises(ValueError):
        _upstream(**over)
