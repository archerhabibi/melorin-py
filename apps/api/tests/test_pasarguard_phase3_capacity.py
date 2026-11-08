"""PasarGuard Phase 3 / PG-08: real destination health (group -> host -> node), the sell-guard and capacity sources/alerts."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from melorin.kernel.models.vpn import Panel, Server
from melorin.modules.catalog.allocation.routing import Candidate, select_allocation
from melorin.modules.eventcenter.rules import server_capacity_text
from melorin.modules.vpn import capacity as cap
from melorin.modules.vpn.adapters.base import Capabilities, ErrorKind, PanelError

GROUP = {"id": 1, "name": "VIP1", "is_disabled": False, "inbound_tags": ["vless", "trojan"], "total_users": 7}
HOSTS = [{"inbound_tag": "vless", "is_disabled": False}, {"inbound_tag": "trojan", "is_disabled": False}]
NODES = [{"id": 1, "status": "connected", "core_config_id": 1}]


# ------------------------------------------------------------------------------------------------------------- pure rules
def test_healthy_group_is_sellable_with_hosts_and_nodes_counted():
    a = cap.assess_group(GROUP, HOSTS, NODES)
    assert a.status == cap.OK and a.sellable and a.score == 100 and a.hosts == 2 and a.nodes == 1 and a.total_users == 7


def test_disabled_group_is_blocked_with_a_reason():
    a = cap.assess_group({**GROUP, "is_disabled": True}, HOSTS, NODES)
    assert a.status == cap.BLOCKED and not a.sellable and "غیرفعال" in a.reasons[0]


def test_group_without_inbounds_or_without_enabled_host_is_blocked():
    assert cap.assess_group({**GROUP, "inbound_tags": []}, HOSTS, NODES).status == cap.BLOCKED
    off = [{"inbound_tag": "vless", "is_disabled": True}, {"inbound_tag": "trojan", "is_disabled": True}]
    blocked = cap.assess_group(GROUP, off, NODES)
    assert blocked.status == cap.BLOCKED and "هاست" in blocked.reasons[0]


def test_group_with_only_failing_nodes_is_blocked_but_unknown_nodes_never_block():
    err = [{"id": 1, "status": "error", "core_config_id": 1}, {"id": 2, "status": "disabled"}]
    assert cap.assess_group(GROUP, HOSTS, err).status == cap.BLOCKED
    assert cap.assess_group(GROUP, HOSTS, []).status == cap.OK  # this credential cannot read nodes: no verdict, fail open


def test_partly_broken_group_is_degraded_and_still_sells():
    nodes = NODES + [{"id": 2, "status": "error", "core_config_id": 1}]
    a = cap.assess_group(GROUP, HOSTS, nodes)
    assert a.status == cap.DEGRADED and a.sellable and 0 < a.score < 100
    one_tag = cap.assess_group(GROUP, HOSTS[:1], NODES)
    assert one_tag.status == cap.DEGRADED and any("trojan" in r for r in one_tag.reasons)


def test_nodes_of_other_cores_do_not_count_when_the_panel_names_the_core():
    cores = cap.tag_cores([{"tag": "vless", "core_config_id": 1}, {"tag": "trojan", "core_config_id": 1}])
    other = [{"id": 9, "status": "connected", "core_config_id": 2}, {"id": 1, "status": "error", "core_config_id": 1}]
    assert cap.assess_group(GROUP, HOSTS, other, cores).status == cap.BLOCKED
    degraded = cap.assess_group(GROUP, HOSTS, other)  # without the core map any connected node counts: still sells, one node is failing
    assert degraded.sellable and degraded.status == cap.DEGRADED


def test_template_sells_while_one_of_its_groups_can_serve():
    groups = {1: cap.assess_group(GROUP, HOSTS, NODES), 2: cap.assess_group({**GROUP, "id": 2, "is_disabled": True}, HOSTS, NODES)}
    assert cap.assess_template({"group_ids": [1, 2]}, groups).status == cap.DEGRADED
    assert cap.assess_template({"group_ids": [2]}, groups).status == cap.BLOCKED
    assert cap.assess_template({"group_ids": [1], "is_disabled": True}, groups).status == cap.BLOCKED
    assert cap.assess_template(None, groups).status == cap.BLOCKED


def test_fill_thresholds():
    assert [cap.fill_state(n, 100) for n in (0, 79, 80, 94, 95, 99, 100, 130)] == [
        "ok", "ok", "warning", "warning", "critical", "critical", "full", "full",
    ]  # fmt: skip
    assert [cap.alert_level(n, 100) for n in (79, 80, 95, 100)] == [0, 80, 95, 100]
    assert cap.fill_state(0, 0) == "full"  # a zero-capacity destination never takes customers


def test_capacity_source_panel_counts_users_created_outside_melorin():
    s = Server(name="s", capacity=10, capacity_source="panel", destination_health={"total_users": 9})
    assert cap.effective_load(s, 2) == 9
    view = cap.capacity_view(s, 2)
    assert view["used"] == 9 and view["outside_melorin"] == 7 and view["state"] == "warning" and view["panel_users"] == 9
    s.capacity_source = "melorin"
    assert cap.effective_load(s, 2) == 2  # default: unchanged behaviour
    s.capacity_source, s.destination_health = "panel", {}
    assert cap.effective_load(s, 2) == 2  # no panel figure yet: never guess


def test_panel_total_is_trusted_only_for_a_single_group_target():
    one = cap.combine([cap.assess_group(GROUP, HOSTS, NODES)])
    two = cap.combine([cap.assess_group(GROUP, HOSTS, NODES), cap.assess_group({**GROUP, "id": 2}, HOSTS, NODES)])
    assert one.total_users == 7 and two.total_users is None


# ------------------------------------------------------------------------------------------------------------- sell-guard
def _cand(**kw) -> Candidate:
    base = dict(
        server_id=uuid.uuid4(), server_name="s", panel_id=uuid.uuid4(), panel_name="p", server_enabled=True, panel_enabled=True,
        panel_healthy=True, allow_test=True, product_codes=(), capacity=10, active_on_server=0, active_on_panel=0,
    )  # fmt: skip
    return Candidate(**{**base, **kw})


def test_unsellable_destination_leaves_selection_with_its_reason_and_others_still_sell():
    bad = _cand(server_name="bad", destination_sellable=False, destination_reason="گروه روی پنل غیرفعال است")
    good = _cand(server_name="good")
    chosen, reasons = select_allocation([bad, good], product_code="P", is_test=False)
    assert chosen is good and any("bad" in r and "قابل فروش نیست" in r and "غیرفعال" in r for r in reasons)
    none, reasons = select_allocation([bad], product_code="P", is_test=False)
    assert none is None and reasons


def test_default_candidate_is_sellable_so_existing_data_behaves_as_before():
    chosen, _ = select_allocation([_cand()], product_code="P", is_test=False)
    assert chosen is not None


# ------------------------------------------------------------------------------------------------------------- the loader
class FakeAdapter:
    kind = "pasarguard"

    def __init__(self, groups=(GROUP,), hosts=HOSTS, nodes=NODES, templates=(), fail=None):
        self.groups, self.hosts, self.nodes, self.templates, self.fail = list(groups), hosts, nodes, list(templates), fail

    def capabilities(self):
        return Capabilities(capacity_ops=True, node_ops=True)

    async def list_groups_full(self):
        if self.fail:
            raise PanelError(ErrorKind.TRANSIENT, "panel down")
        return self.groups

    async def list_hosts(self):
        return self.hosts

    async def list_inbound_details(self):
        return []

    async def list_nodes(self):
        return self.nodes

    async def list_templates(self):
        return self.templates


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


async def _panel_with_servers(s, *targets, capacity=10):
    panel = Panel(name="P", kind="pasarguard", base_url="https://p.example.com", config={}, is_enabled=True, health_status="healthy")
    s.add(panel)
    await s.flush()
    servers = [Server(name=f"S{i}", panel_id=panel.id, capacity=capacity, target=t) for i, t in enumerate(targets)]
    s.add_all(servers)
    await s.commit()
    return panel, servers


async def test_refresh_blocks_a_server_on_a_dead_group_and_reports_the_flip_once(maker):
    async with maker() as s:
        panel, (ok, dead) = await _panel_with_servers(s, {"group_ids": [1]}, {"group_ids": [2]})
        adapter = FakeAdapter(groups=[GROUP, {**GROUP, "id": 2, "is_disabled": True}])
        changes = await cap.refresh_panel(s, panel, adapter)
        await s.commit()
        await s.refresh(ok), await s.refresh(dead)
        assert ok.sellable and not dead.sellable and "غیرفعال" in dead.sellable_reason
        assert dead.destination_health["status"] == cap.BLOCKED and dead.destination_health["check"] == "ok"
        assert cap.panel_users(ok) == 7 and ok.capacity_checked_at is not None
        assert [(c.server, c.kind, c.new) for c in changes] == [("S1", "sellable", "blocked")]
        again = await cap.refresh_panel(s, panel, adapter)
        assert again == []  # a standing condition is announced once, not every 2 minutes
        adapter.groups[1]["is_disabled"] = False
        back = await cap.refresh_panel(s, panel, adapter)
        assert [(c.server, c.new) for c in back] == [("S1", "sellable")] and dead.sellable


async def test_failed_or_unknown_checks_fail_open_and_keep_the_last_verdict(maker):
    async with maker() as s:
        panel, (a, b) = await _panel_with_servers(s, {"group_ids": [1]}, {"group_ids": [404]})
        await cap.refresh_panel(s, panel, FakeAdapter())
        assert a.sellable and not b.sellable  # group 404 does not exist on the panel: a positive finding
        down = await cap.refresh_panel(s, panel, FakeAdapter(fail=True))
        assert down == [] and a.sellable and not b.sellable  # panel error: nothing flips
        assert a.destination_health["check"] == "failed" and a.destination_health["status"] == cap.OK


async def test_server_without_a_checkable_target_is_never_touched(maker):
    async with maker() as s:
        panel, (inherit,) = await _panel_with_servers(s, None)
        assert await cap.refresh_panel(s, panel, FakeAdapter()) == []
        assert inherit.sellable and inherit.capacity_checked_at is not None


async def test_template_target_uses_the_templates_groups(maker):
    async with maker() as s:
        panel, (srv,) = await _panel_with_servers(s, {"user_template_id": 5})
        tpl = {"id": 5, "group_ids": [2], "is_disabled": False}
        await cap.refresh_panel(s, panel, FakeAdapter(groups=[GROUP, {**GROUP, "id": 2, "is_disabled": True}], templates=[tpl]))
        assert not srv.sellable
        await cap.refresh_panel(s, panel, FakeAdapter(groups=[GROUP], templates=[{**tpl, "group_ids": [1]}]))
        assert srv.sellable


async def test_capacity_alerts_climb_once_per_threshold_and_reset_when_load_falls(maker):
    async with maker() as s:
        panel, (srv,) = await _panel_with_servers(s, {"group_ids": [1]}, capacity=10)
        srv.capacity_source = "panel"
        await s.commit()
        seen = []
        for users in (5, 8, 8, 10, 3, 9):
            adapter = FakeAdapter(groups=[{**GROUP, "total_users": users}])
            seen.append([c.new for c in await cap.refresh_panel(s, panel, adapter) if c.kind == "capacity"])
        assert seen == [[], ["80"], [], ["100"], [], ["80"]]  # 80% once, 100% once, fall back, 80% announced again


def test_event_center_text_groups_everything_into_one_message():
    changes = [
        cap.Change("S1", "sellable", "sellable", "blocked", "گروه روی پنل غیرفعال است"),
        cap.Change("S2", "sellable", "blocked", "sellable"),
        cap.Change("S3", "capacity", "0", "95"),
    ]
    text = server_capacity_text("P", changes)
    assert "S1" in text and "غیرفعال" in text and "S2" in text and "۹۵٪" in text and text.count("\n") >= 3
    assert server_capacity_text("P", []) is None
