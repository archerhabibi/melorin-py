"""Destination (target) rules, merge over the panel config, and the admin endpoints that use them."""

import types
import uuid

import pytest
from sqlalchemy import select

import melorin.models  # noqa: F401  (registers every table)
from melorin.core import db
from melorin.core.errors import AppError
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import Panel, Server
from melorin.modules.admin import panels as admin_panels
from melorin.modules.admin import targets as admin_targets
from melorin.modules.admin.schemas import CreateServer
from melorin.modules.panel_integrations.targets import (
    capacity_label,
    effective_destination,
    merge_config,
    normalize_target,
    validate_target,
)

ADMIN = types.SimpleNamespace(id=uuid.uuid4())


# ---------------------------------------------------------------- pure rules


@pytest.mark.parametrize(
    "kind,target,ok",
    [
        ("pasarguard", {"group_ids": [2, 3]}, True),
        ("pasarguard", {"user_template_id": 5}, True),
        ("pasarguard", {"user_template_id": 5, "limits_from": "template"}, True),
        ("pasarguard", {"group_ids": [2], "user_template_id": 5}, False),  # exactly one of the two
        ("pasarguard", {"group_ids": []}, False),
        ("pasarguard", {"group_ids": [0]}, False),
        ("pasarguard", {"group_ids": [2], "limits_from": "product"}, False),  # limits_from only with a template
        ("pasarguard", {"inbound_ids": [1]}, False),
        ("sanaei", {"inbound_ids": [4, 5]}, True),
        ("sanaei", {"inbound_ids": []}, False),
        ("sanaei", {"group_ids": [1]}, False),
        ("mock", {"group_ids": [1]}, False),
        ("pasarguard", None, True),  # inherit
        ("sanaei", {}, True),
    ],
)
def test_target_validation_matrix(kind, target, ok):
    assert (validate_target(kind, normalize_target(target)) == []) is ok


def test_legacy_sanaei_accepts_exactly_one_inbound():
    assert validate_target("sanaei", {"inbound_ids": [4]}, api_style="legacy") == []
    assert validate_target("sanaei", {"inbound_ids": [4, 5]}, api_style="legacy")


def test_normalize_makes_ints_and_drops_duplicates_and_empty_means_inherit():
    assert normalize_target({"group_ids": ["2", 2, 3]}) == {"group_ids": [2, 3]}
    assert normalize_target({}) is None and normalize_target(None) is None


def test_target_replaces_every_destination_key_of_the_panel_config_but_keeps_the_rest():
    panel = {"user_template_id": 9, "limits_from": "template", "sub_base_url": "https://s", "verify_tls": True}
    merged = merge_config(panel, {"group_ids": [3]})
    assert merged == {"group_ids": [3], "sub_base_url": "https://s", "verify_tls": True}
    assert merge_config(panel, None) == panel  # no target: the panel config as it was
    assert panel["user_template_id"] == 9  # the input is never mutated


def test_effective_destination_exposes_destination_keys_only():
    cfg = {"group_ids": [1], "sub_base_url": "https://s", "password": "x"}
    assert effective_destination("pasarguard", cfg, {"group_ids": [7]}) == {"group_ids": [7]}
    assert effective_destination("pasarguard", cfg, None) == {"group_ids": [1]}


def test_capacity_label_follows_the_target_kind():
    assert capacity_label("pasarguard", {"group_ids": [1]}) == "ظرفیت گروه"
    assert capacity_label("pasarguard", {"user_template_id": 1}) == "ظرفیت تمپلیت"
    assert capacity_label("sanaei", {"inbound_ids": [1]}) == "ظرفیت اینباند"
    assert capacity_label("sanaei", None) == "ظرفیت مقصد"


# ---------------------------------------------------------------- admin endpoints


@pytest.fixture
async def session(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/targets.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=[Panel.__table__, Server.__table__, AuditEvent.__table__]))
    async with db.session_factory()() as s:
        yield s
    await db.engine().dispose()


async def _panel(s, kind="pasarguard", config=None):
    p = Panel(name="main", kind=kind, base_url="http://x", is_enabled=True, health_status="healthy", config=config or {"group_ids": [2]})
    s.add(p)
    await s.commit()
    return p


@pytest.fixture
def no_panel_listing(monkeypatch):
    async def none(_panel):
        return None

    monkeypatch.setattr(admin_targets, "fetch_listing", none)
    monkeypatch.setattr(admin_panels, "fetch_listing", none, raising=False)


async def test_an_invalid_target_is_refused_with_422_and_nothing_is_stored(session, no_panel_listing):
    p = await _panel(session)
    body = CreateServer(name="DE-1", panel_id=p.id, capacity=50, target={"group_ids": [1], "user_template_id": 2})
    with pytest.raises(AppError) as exc:
        await admin_panels.create_server(body, ADMIN, session)
    assert exc.value.status == 422 and exc.value.code == "INVALID_TARGET"
    assert (await session.scalars(select(Server))).all() == []


async def test_a_valid_target_is_stored_normalised(session, no_panel_listing):
    p = await _panel(session)
    await admin_panels.create_server(
        CreateServer(name="DE-1", panel_id=p.id, capacity=50, target={"group_ids": ["3", 3, 4]}), ADMIN, session
    )
    s = (await session.scalars(select(Server))).one()
    assert s.target == {"group_ids": [3, 4]} and s.last_assigned_at is None


async def test_wizard_creates_one_destination_per_group_skips_existing_and_uses_default_capacity(session, monkeypatch):
    p = await _panel(session)

    async def listing(_panel):
        return {"kind": "pasarguard", "groups": [{"id": i, "name": f"g{i}", "disabled": False} for i in range(1, 25)], "templates": []}

    monkeypatch.setattr(admin_targets, "fetch_listing", listing)
    body = admin_targets.ServersFromTargets(kind="group", ids=[1, 2, 3])
    out = await admin_targets.create_servers_from_targets(p.id, body, ADMIN, session)
    assert [c["target"] for c in out["created"]] == [{"group_ids": [1]}, {"group_ids": [2]}, {"group_ids": [3]}]
    rows = (await session.scalars(select(Server))).all()
    assert {s.capacity for s in rows} == {admin_targets.DEFAULT_CAPACITY}
    again = await admin_targets.create_servers_from_targets(
        p.id, admin_targets.ServersFromTargets(kind="group", ids=[3, 4]), ADMIN, session
    )
    assert len(again["created"]) == 1 and len(again["skipped"]) == 1  # sync: only the new group is added


async def test_wizard_refuses_a_kind_the_panel_does_not_have(session, no_panel_listing):
    p = await _panel(session)
    with pytest.raises(AppError) as exc:
        await admin_targets.create_servers_from_targets(p.id, admin_targets.ServersFromTargets(kind="inbound", ids=[1]), ADMIN, session)
    assert exc.value.status == 422


async def test_sanaei_inbounds_can_be_one_set_or_one_each(session, no_panel_listing):
    p = await _panel(session, kind="sanaei", config={"inbound_ids": [1]})
    one = await admin_targets.create_servers_from_targets(
        p.id, admin_targets.ServersFromTargets(kind="inbound", ids=[4, 5], group_as_one=True), ADMIN, session
    )
    assert [c["target"] for c in one["created"]] == [{"inbound_ids": [4, 5]}]
    each = await admin_targets.create_servers_from_targets(
        p.id, admin_targets.ServersFromTargets(kind="inbound", ids=[6, 7]), ADMIN, session
    )
    assert [c["target"] for c in each["created"]] == [{"inbound_ids": [6]}, {"inbound_ids": [7]}]


async def test_panel_targets_endpoint_marks_groups_already_used_and_reports_an_unreachable_panel(session, monkeypatch):
    p = await _panel(session)
    session.add(Server(name="S", panel_id=p.id, capacity=10, target={"group_ids": [2]}))
    await session.commit()

    async def listing(_panel):
        return {"kind": "pasarguard", "groups": [{"id": 2, "name": "a"}, {"id": 3, "name": "b"}], "templates": []}

    monkeypatch.setattr(admin_targets, "fetch_listing", listing)
    out = await admin_targets.panel_targets(p.id, ADMIN, session)
    used = {g["id"]: [u["name"] for u in g["used_by"]] for g in out["groups"]}
    assert used == {2: ["S"], 3: []}

    async def down(_panel):
        return None

    monkeypatch.setattr(admin_targets, "fetch_listing", down)
    with pytest.raises(AppError) as exc:
        await admin_targets.panel_targets(p.id, ADMIN, session)
    assert exc.value.status == 502
