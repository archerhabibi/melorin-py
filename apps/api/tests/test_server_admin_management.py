import types
import uuid

import pytest

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.admin import router as r
from melorin.modules.admin.schemas import CreateServer, PanelState, UpdateServer
from melorin.modules.catalog.models import Product
from melorin.modules.system.models import AuditEvent
from melorin.modules.vpn.models import Panel, Server, VpnAccount

ADMIN = types.SimpleNamespace(id=uuid.uuid4())


@pytest.fixture
async def session(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/servers.db")
    async with db.engine().begin() as conn:
        tables = [m.__table__ for m in (Panel, Server, VpnAccount, Product, AuditEvent)]
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=tables))
    async with db.session_factory()() as s:
        yield s
    await db.engine().dispose()


async def _panel(session, name="P1"):
    p = Panel(name=name, kind="mock", base_url="https://p.example.com", config={})
    session.add(p)
    await session.flush()
    return p


async def _product(session, code):
    session.add(Product(code=code, name=code, duration_days=30, traffic_gb=10, main_price=1, reseller_price=1, currency="IRT"))
    await session.flush()


async def _account(session, server_id, panel_id, status):
    n = str(uuid.uuid4())[:8]
    session.add(
        VpnAccount(
            username=f"u{n}",
            user_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            order_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            server_id=server_id,
            panel_id=panel_id,
            status=status,
        )
    )
    await session.flush()


async def _server(session, panel, **over):
    body = dict(name="DE-1", panel_id=panel.id, capacity=10)
    body.update(over)
    out = await r.create_server(CreateServer(**body), ADMIN, session)
    return out["id"]


async def test_list_includes_panel_name_and_account_counts(session):
    p = await _panel(session)
    sid = await _server(session, p)
    other = await _server(session, p, name="DE-2")
    listed = {x.id: x for x in await r.servers(ADMIN, session)}
    assert listed[sid].panel_name == "P1" and (listed[sid].active_accounts, listed[sid].total_accounts, listed[sid].is_enabled) == (
        0,
        0,
        True,
    )
    await _account(session, sid, p.id, "active")
    await _account(session, sid, p.id, "active")
    await _account(session, sid, p.id, "expired")
    await session.commit()
    listed = {x.id: x for x in await r.servers(ADMIN, session)}
    assert (listed[sid].active_accounts, listed[sid].total_accounts) == (2, 3)
    assert (listed[other].active_accounts, listed[other].total_accounts) == (0, 0)


async def test_update_is_partial_and_audited(session):
    p = await _panel(session)
    sid = await _server(session, p, location="DE", product_codes=None)
    out = await r.update_server(sid, UpdateServer(capacity=50), ADMIN, session)
    assert out.capacity == 50 and out.name == "DE-1" and out.location == "DE"  # untouched fields stay
    out = await r.update_server(sid, UpdateServer(location=None, allow_test=False), ADMIN, session)
    assert out.location is None and out.allow_test is False
    from sqlalchemy import select

    events = (await session.scalars(select(AuditEvent).where(AuditEvent.action == "server.updated"))).all()
    assert len(events) == 2 and events[0].data["changed"] == ["capacity"]


async def test_update_noop_writes_no_audit_event(session):
    p = await _panel(session)
    sid = await _server(session, p)
    await r.update_server(sid, UpdateServer(name="DE-1"), ADMIN, session)
    from sqlalchemy import select

    assert (await session.scalars(select(AuditEvent).where(AuditEvent.action == "server.updated"))).all() == []


async def test_update_rejects_null_required_fields_and_blank_name(session):
    p = await _panel(session)
    sid = await _server(session, p)
    for body in (UpdateServer.model_validate({"name": None}), UpdateServer.model_validate({"capacity": None}), UpdateServer(name="   ")):
        with pytest.raises(AppError) as e:
            await r.update_server(sid, body, ADMIN, session)
        assert e.value.status == 422


async def test_product_codes_are_normalised_and_validated_on_update(session):
    p = await _panel(session)
    await _product(session, "vpn-1m")
    await _product(session, "vpn-3m")
    sid = await _server(session, p)
    out = await r.update_server(sid, UpdateServer(product_codes=[" vpn-3m", "vpn-1m", "vpn-1m"]), ADMIN, session)
    assert out.product_codes == ["vpn-1m", "vpn-3m"]
    with pytest.raises(AppError) as e:
        await r.update_server(sid, UpdateServer(product_codes=["nope"]), ADMIN, session)
    assert e.value.code == "UNKNOWN_PRODUCT_CODES"
    out = await r.update_server(sid, UpdateServer(product_codes=[]), ADMIN, session)
    assert out.product_codes is None  # empty list = all products


async def test_moving_server_to_other_panel_is_blocked_once_it_has_accounts(session):
    p1, p2 = await _panel(session, "P1"), await _panel(session, "P2")
    sid = await _server(session, p1)
    out = await r.update_server(sid, UpdateServer(panel_id=p2.id), ADMIN, session)  # no accounts yet: allowed
    assert out.panel_id == p2.id and out.panel_name == "P2"
    with pytest.raises(AppError) as e:
        await r.update_server(sid, UpdateServer(panel_id=uuid.uuid4()), ADMIN, session)
    assert e.value.status == 404  # unknown panel
    await _account(session, sid, p2.id, "expired")
    await session.commit()
    with pytest.raises(AppError) as e:
        await r.update_server(sid, UpdateServer(panel_id=p1.id), ADMIN, session)
    assert e.value.code == "SERVER_HAS_ACCOUNTS" and e.value.status == 409
    out = await r.update_server(sid, UpdateServer(panel_id=p2.id, capacity=7), ADMIN, session)  # same panel: not a move
    assert out.capacity == 7


async def test_unknown_server_is_404(session):
    with pytest.raises(AppError) as e:
        await r.update_server(uuid.uuid4(), UpdateServer(capacity=5), ADMIN, session)
    assert e.value.status == 404
    with pytest.raises(AppError):
        await r.set_server_state(uuid.uuid4(), PanelState(is_enabled=False), ADMIN, session)


async def test_server_enable_disable_is_idempotent_and_reflected_in_list(session):
    p = await _panel(session)
    sid = await _server(session, p)
    assert (await r.set_server_state(sid, PanelState(is_enabled=False), ADMIN, session))["is_enabled"] is False
    assert (await r.set_server_state(sid, PanelState(is_enabled=False), ADMIN, session))["is_enabled"] is False
    assert [x.is_enabled for x in await r.servers(ADMIN, session)] == [False]
    from sqlalchemy import select

    assert len((await session.scalars(select(AuditEvent).where(AuditEvent.action == "server.disabled"))).all()) == 1
    assert (await session.get(Server, sid)).is_enabled is False
