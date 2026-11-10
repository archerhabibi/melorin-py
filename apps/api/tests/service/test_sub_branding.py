"""PG-12: subscription-page branding is validated, saved in Melorin only, and written to the panel by an explicit, verified, audited action."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import open_schema_engine
from melorin.core.errors import AppError
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent
from melorin.kernel.models.vpn import Panel, PanelAdmin
from melorin.modules.panelops import sub_branding
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from melorin.modules.vpn.adapters.pasarguard import PasarGuardAdapter
from test_pasarguard_service_db import seed

OURS = set(sub_branding.VARIABLES.values())


# ------------------------------------------------------------------------------------------------ validation (pure)
def test_clean_accepts_plain_text_and_https_links_and_refuses_markup():
    ok = sub_branding.clean(
        {"display_name": "فروشگاه آرش", "support_url": "https://t.me/arash", "logo_url": "https://cdn.example.com/logo.PNG"}
    )
    assert ok["display_name"] == "فروشگاه آرش" and ok["support_url"].startswith("https://")
    assert sub_branding.clean({"support_url": "tg://resolve?domain=arash"})["support_url"].startswith("tg://")
    assert sub_branding.clean({"display_name": ""}) == {"display_name": ""}  # clears
    assert sub_branding.clean({"display_name": None}) == {}  # unchanged
    for bad in (
        {"display_name": "<script>alert(1)</script>"},
        {"display_name": 'a"b'},
        {"display_name": "x" * 65},
        {"support_url": "http://plain.example.com"},
        {"support_url": "javascript:alert(1)"},
        {"support_url": "https://user:pw@example.com"},
        {"logo_url": "https://cdn.example.com/logo.html"},
        {"logo_url": "data:image/png;base64,AAAA"},
        {"display_name": "{url}"},  # the panel would expand it as a placeholder
        {"display_name": "a{b"},
        {"support_url": "https://x.example.com/{username}"},
        {"sub_template": "<html>"},  # Melorin never takes a template from a store
        {"custom_variables": {"a": "b"}},
    ):
        with pytest.raises(AppError):
            sub_branding.clean(bad)


def test_save_keeps_other_branding_keys_and_empty_removes_the_block():
    store = Store(name="s", slug="s", kind="reseller", branding={"colors": {"a": 1}})
    sub_branding.save(store, {"display_name": "A", "support_url": "https://x.example.com/s"})
    assert store.branding["colors"] == {"a": 1} and sub_branding.get(store)["display_name"] == "A"
    sub_branding.save(store, {"display_name": ""})  # one field cleared, one kept
    assert set(sub_branding.get(store)) == {"support_url"}
    sub_branding.save(store, {"support_url": ""})
    assert "sub" not in store.branding and store.branding["colors"] == {"a": 1}
    assert sub_branding.wanted_variables(store) == {}


def test_parse_custom_variables_reads_the_panels_list_and_tolerates_other_shapes():
    p = PasarGuardAdapter.parse_custom_variables
    # PasarGuard 5.6.0: a list of {key, value}, keys upper-cased
    assert p([{"key": "melorin_brand_name", "value": "A"}, {"key": "THEME", "value": "dark"}, {"key": "", "value": "x"}, "junk"]) == {
        "MELORIN_BRAND_NAME": "A",
        "THEME": "dark",
    }
    assert p('[{"key": "a", "value": "1"}]') == {"A": "1"} and p([]) == {}
    # tolerated, never produced by 5.6.0
    assert p({"a": "1", "b": 2, "c": {"x": 1}}) == {"A": "1", "B": "2"}
    assert p('{"a": "1"}') == {"A": "1"} and p("") == {} and p("not json") == {} and p(None) == {}


@pytest.mark.asyncio
async def test_write_custom_variables_sends_the_list_the_panel_accepts_not_an_object(monkeypatch):
    """PasarGuard 5.6.0 answers 422 ``list_type`` to an object. The wire body must be a sorted list of upper-case {key, value}."""
    a = PasarGuardAdapter("https://p.example.com", {"username": "admin", "password": "pw"}, {})
    seen: dict = {}

    async def fake_req(method, path, **kw):
        seen.update(method=method, path=path, **kw)
        return {}

    monkeypatch.setattr(a, "_req", fake_req)
    await a.write_custom_variables(7, {"melorin_support_url": "https://t.me/a", "MELORIN_BRAND_NAME": "Arash"})
    assert seen["method"] == "PUT" and seen["path"] == "/api/admin/by-id/7"
    assert seen["json"] == {
        "custom_variables": [
            {"key": "MELORIN_BRAND_NAME", "value": "Arash"},
            {"key": "MELORIN_SUPPORT_URL", "value": "https://t.me/a"},
        ]
    }
    await a.write_custom_variables(7, {})  # clearing = an empty list, still a list
    assert seen["json"] == {"custom_variables": []}


def test_our_variable_names_are_already_in_the_form_the_panel_stores():
    assert all(v == v.upper() and v.startswith("MELORIN_") for v in sub_branding.VARIABLES.values())


# ------------------------------------------------------------------------------------------------ apply / revert (fake panel)
class FakeAdmin:
    """Holds one admin's custom_variables. ``keep=False`` simulates a panel that ignores the write."""

    def __init__(self, variables=None, *, keep=True, fail_write=False):
        self.vars, self.keep, self.fail_write = dict(variables or {}), keep, fail_write
        self.writes: list[dict] = []

    async def read_custom_variables(self, username):
        return dict(self.vars)

    async def write_custom_variables(self, remote_id, variables):
        if self.fail_write:
            raise PanelError(ErrorKind.PERMANENT, "403 forbidden")
        self.writes.append(dict(variables))
        if self.keep:
            self.vars = dict(variables)
        return {}

    async def close(self):
        pass


@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


async def _world(maker):
    await seed(maker, [])
    async with maker() as s:
        panel = (await s.scalars(select(Panel))).one()
        panel.kind = "pasarguard"
        row = (await s.scalars(select(PanelAdmin))).one()
        row.remote_id = 7
        store = await s.get(Store, row.store_id)
        sub_branding.save(
            store, {"display_name": "Arash VPN", "support_url": "https://t.me/arash", "logo_url": "https://cdn.example.com/a.png"}
        )
        await s.commit()
        return panel.id, store.id


async def _use(maker, monkeypatch, fake):
    monkeypatch.setattr(sub_branding.registry, "build_adapter", lambda panel, credentials=None: fake)
    pid, sid = await _world(maker)
    return pid, sid


@pytest.mark.asyncio
async def test_apply_writes_only_our_three_keys_keeps_foreign_ones_and_audits_without_values(maker, monkeypatch):
    fake = FakeAdmin({"THEME": "dark", "MELORIN_BRAND_NAME": "old"})
    pid, sid = await _use(maker, monkeypatch, fake)
    async with maker() as s:
        panel, store = await s.get(Panel, pid), await s.get(Store, sid)
        pre = await sub_branding.preview(s, store, panel)
        assert (
            pre["live"] and pre["in_sync"] is False and pre["other_keys_kept"] == ["THEME"] and fake.writes == []
        )  # preview writes nothing
        out = await sub_branding.apply(s, store, panel, actor_id=None)
        assert out["applied"] and out["changed"] and set(out["keys"]) == OURS
        assert fake.vars["THEME"] == "dark" and fake.vars["MELORIN_BRAND_NAME"] == "Arash VPN" and OURS <= set(fake.vars)
        assert (await sub_branding.preview(s, store, panel))["in_sync"] is True
        events = (await s.scalars(select(AuditEvent).where(AuditEvent.action == "panel.sub_branding.applied"))).all()
        assert len(events) == 1 and "Arash" not in json.dumps(events[0].data) and "t.me" not in json.dumps(events[0].data)
        again = await sub_branding.apply(s, store, panel)  # idempotent: no second write
        assert again["changed"] is False and len(fake.writes) == 1
        assert store.branding["sub_applied"][str(pid)]["digest"] == out["digest"]


@pytest.mark.asyncio
async def test_apply_restores_the_previous_values_when_the_panel_does_not_keep_them(maker, monkeypatch):
    fake = FakeAdmin({"THEME": "dark"}, keep=False)
    pid, sid = await _use(maker, monkeypatch, fake)
    async with maker() as s:
        panel, store = await s.get(Panel, pid), await s.get(Store, sid)
        with pytest.raises(AppError) as e:
            await sub_branding.apply(s, store, panel)
        assert e.value.code == "BRANDING_APPLY_FAILED"
        assert fake.writes[-1] == {"THEME": "dark"}  # the restore was attempted
        assert "sub_applied" not in (store.branding or {})


@pytest.mark.asyncio
async def test_a_refusing_panel_is_reported_and_nothing_is_marked_applied(maker, monkeypatch):
    fake = FakeAdmin(fail_write=True)
    pid, sid = await _use(maker, monkeypatch, fake)
    async with maker() as s:
        panel, store = await s.get(Panel, pid), await s.get(Store, sid)
        with pytest.raises(AppError) as e:
            await sub_branding.apply(s, store, panel)
        assert e.value.code == "BRANDING_APPLY_FAILED" and "sub_applied" not in (store.branding or {})


@pytest.mark.asyncio
async def test_apply_needs_something_to_apply_and_a_ready_store_admin(maker, monkeypatch):
    fake = FakeAdmin()
    pid, sid = await _use(maker, monkeypatch, fake)
    async with maker() as s:
        panel, store = await s.get(Panel, pid), await s.get(Store, sid)
        sub_branding.save(store, {"display_name": "", "support_url": "", "logo_url": ""})
        with pytest.raises(AppError) as e:
            await sub_branding.apply(s, store, panel)
        assert e.value.code == "BRANDING_EMPTY"
        sub_branding.save(store, {"display_name": "A"})
        row = (await s.scalars(select(PanelAdmin))).one()
        row.status = "pending"
        with pytest.raises(AppError) as e2:
            await sub_branding.apply(s, store, panel)
        assert e2.value.code == "STORE_ADMIN_NOT_READY" and fake.writes == []
        panel.kind = "sanaei"
        with pytest.raises(AppError) as e3:
            await sub_branding.apply(s, store, panel)
        assert e3.value.code == "NOT_PASARGUARD"


@pytest.mark.asyncio
async def test_revert_removes_only_our_keys(maker, monkeypatch):
    fake = FakeAdmin({"THEME": "dark"})
    pid, sid = await _use(maker, monkeypatch, fake)
    async with maker() as s:
        panel, store = await s.get(Panel, pid), await s.get(Store, sid)
        await sub_branding.apply(s, store, panel)
        out = await sub_branding.revert(s, store, panel)
        assert out["applied"] is False and set(out["removed"]) == OURS
        assert fake.vars == {"THEME": "dark"} and "sub_applied" not in (store.branding or {})


@pytest.mark.asyncio
async def test_unreachable_panel_gives_no_numbers_and_a_503_on_apply(maker, monkeypatch):
    class Down(FakeAdmin):
        async def read_custom_variables(self, username):
            raise PanelError(ErrorKind.TRANSIENT, "timeout")

    pid, sid = await _use(maker, monkeypatch, Down())
    async with maker() as s:
        panel, store = await s.get(Panel, pid), await s.get(Store, sid)
        assert (await sub_branding.preview(s, store, panel))["live"] is False
        with pytest.raises(AppError) as e:
            await sub_branding.apply(s, store, panel)
        assert e.value.status == 503
