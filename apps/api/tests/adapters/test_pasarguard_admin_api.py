"""PasarGuard Phase 1 admin API (PG-01 / PG-04 / PG-05): node view, issue list + safe actions, discovered panel users."""

from __future__ import annotations

import datetime as dt

from _db import make_order, make_product, make_user
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.db import utcnow
from melorin.kernel.models.vpn import Panel, PanelNode, PanelOrphan, ReconciliationIssue, VpnAccount
from melorin.modules.panelops import reconciliation_actions
from melorin.modules.vpn import issues

BASE = "/api/v1/admin"


async def _login(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _world(maker, main_store, *, kinds=(issues.MISSING,)):
    """One panel, one account with ``kinds`` open issues, two nodes and one orphan."""
    async with maker() as s:
        user, product = await make_user(s), await make_product(s)
        order = await make_order(s, user=user, store=main_store, product=product)
        panel = Panel(name="pg", kind="pasarguard", base_url="https://p.example.com", health_status="degraded", last_health_at=utcnow())
        panel.health_detail = {"layer": 2, "sellable": True, "nodes": {"total": 2, "connected": 1, "error": 1}}
        s.add(panel)
        await s.flush()
        acc = VpnAccount(
            username="alice",
            user_id=user.id,
            store_id=main_store.id,
            order_id=order.id,
            product_id=product.id,
            panel_id=panel.id,
            panel_ref="5",
            status="active",
        )
        s.add(acc)
        await s.flush()
        rows = [
            ReconciliationIssue(
                vpn_account_id=acc.id,
                kind=k,
                status="open",
                occurrences=2,
                last_seen_at=utcnow(),
                details={"expected": "ml_main", "panel": "x"},
            )
            for k in kinds
        ]
        s.add_all(rows)
        s.add_all(
            [
                PanelNode(panel_id=panel.id, remote_id=1, name="ok-node", status="connected", status_changed_at=utcnow()),
                PanelNode(
                    panel_id=panel.id,
                    remote_id=2,
                    name="bad-node",
                    status="error",
                    message="CERTIFICATE_VERIFY_FAILED (self-signed)",
                    status_changed_at=utcnow(),
                ),
            ]
        )
        orphan = PanelOrphan(
            panel_id=panel.id, username="rahim", status="open", owner_username="Ajdar", first_seen_at=utcnow(), last_seen_at=utcnow()
        )
        s.add(orphan)
        await s.commit()
        return {"panel": panel.id, "account": acc.id, "issues": {r.kind: r.id for r in rows}, "orphan": orphan.id}


async def test_every_endpoint_needs_an_admin():
    async with api_client() as (c, _, __):
        for method, path in (
            ("get", "/reconciliation/issues"),
            ("get", "/reconciliation/summary"),
            ("get", "/panel-orphans"),
            ("get", "/panels/00000000-0000-0000-0000-000000000001/nodes"),
            ("post", "/panels/00000000-0000-0000-0000-000000000001/reconcile"),
        ):
            r = await getattr(c, method)(BASE + path)
            assert r.status_code in (401, 403), (path, r.status_code)


async def test_nodes_view_shows_the_reason_and_a_fix_hint(monkeypatch):
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        w = await _world(maker, main)
        body = (await c.get(f"{BASE}/panels/{w['panel']}/nodes", headers=h)).json()
        assert body["health_status"] == "degraded" and body["detail"]["nodes"]["error"] == 1
        by = {n["name"]: n for n in body["nodes"]}
        assert by["ok-node"]["hint"] is None
        assert "server_ca" in by["bad-node"]["hint"] and "self-signed" in by["bad-node"]["message"]
        assert (await c.get(f"{BASE}/panels/00000000-0000-0000-0000-000000000009/nodes", headers=h)).status_code == 404


async def test_issue_list_summary_and_filters():
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        await _world(maker, main, kinds=(issues.MISSING, issues.OWNER_MISMATCH))
        listed = (await c.get(f"{BASE}/reconciliation/issues", headers=h)).json()
        assert listed["total"] == 2 and {i["kind"] for i in listed["items"]} == {issues.MISSING, issues.OWNER_MISMATCH}
        first = next(i for i in listed["items"] if i["kind"] == issues.OWNER_MISMATCH)
        assert first["username"] == "alice" and first["panel_name"] == "pg" and "fix_owner" in first["allowed_actions"]
        only = (await c.get(f"{BASE}/reconciliation/issues", params={"kind": issues.MISSING}, headers=h)).json()
        assert only["total"] == 1
        summary = (await c.get(f"{BASE}/reconciliation/summary", headers=h)).json()
        assert summary["open_total"] == 2 and summary["open"][issues.MISSING] == 1 and summary["orphans_open"] == 1
        assert (await c.get(f"{BASE}/reconciliation/issues", params={"status": "bogus"}, headers=h)).status_code == 422
        assert (await c.get(f"{BASE}/reconciliation/issues", params={"kind": "bogus"}, headers=h)).status_code == 422


async def test_ignoring_an_issue_needs_a_reason_and_is_audited():
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        w = await _world(maker, main)
        url = f"{BASE}/reconciliation/issues/{w['issues'][issues.MISSING]}/action"
        assert (await c.post(url, json={"action": "ignore"}, headers=h)).status_code == 422
        r = await c.post(url, json={"action": "ignore", "reason": "manual test account"}, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "ignored" and r.json()["allowed_actions"] == []
        assert "manual test account" in r.json()["resolution"]
        again = await c.post(url, json={"action": "resolve"}, headers=h)
        assert again.status_code == 409  # a closed issue takes no further action


async def test_archive_is_only_for_missing_accounts_and_never_touches_the_panel():
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        w = await _world(maker, main, kinds=(issues.MISSING, issues.OWNER_MISMATCH))
        wrong = await c.post(
            f"{BASE}/reconciliation/issues/{w['issues'][issues.OWNER_MISMATCH]}/action", json={"action": "archive_account"}, headers=h
        )
        assert wrong.status_code == 409
        ok = await c.post(
            f"{BASE}/reconciliation/issues/{w['issues'][issues.MISSING]}/action",
            json={"action": "archive_account", "reason": "deleted by hand"},
            headers=h,
        )
        assert ok.status_code == 200 and ok.json()["status"] == "resolved"
        async with maker() as s:
            acc = await s.get(VpnAccount, w["account"])
        assert acc.status == "archived" and acc.archived_at is not None


async def test_fix_owner_sets_the_expected_owner_on_the_panel(monkeypatch):
    calls = []

    class Stub:
        def capabilities(self):
            from melorin.modules.vpn.adapters.base import Capabilities

            return Capabilities(bulk_ops=True)

        async def bulk_set_owner(self, refs, owner):
            calls.append((refs, owner))
            return len(refs)

        async def close(self):
            return None

    monkeypatch.setattr(reconciliation_actions, "build_adapter", lambda panel: Stub())
    monkeypatch.setattr(reconciliation_actions, "seed_adapter", lambda adapter, account: adapter)
    monkeypatch.setattr(reconciliation_actions, "supports", lambda adapter, cap: True)
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        w = await _world(maker, main, kinds=(issues.OWNER_MISMATCH,))
        r = await c.post(
            f"{BASE}/reconciliation/issues/{w['issues'][issues.OWNER_MISMATCH]}/action", json={"action": "fix_owner"}, headers=h
        )
        assert r.status_code == 200 and r.json()["status"] == "resolved" and "ml_main" in r.json()["resolution"]
    assert calls == [(["5"], "ml_main")]


async def test_fix_owner_without_the_permission_is_a_clear_409_and_the_issue_stays_open(monkeypatch):
    class Stub:
        async def close(self):
            return None

    monkeypatch.setattr(reconciliation_actions, "build_adapter", lambda panel: Stub())
    monkeypatch.setattr(reconciliation_actions, "seed_adapter", lambda adapter, account: adapter)
    monkeypatch.setattr(reconciliation_actions, "supports", lambda adapter, cap: False)
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        w = await _world(maker, main, kinds=(issues.OWNER_MISMATCH,))
        r = await c.post(
            f"{BASE}/reconciliation/issues/{w['issues'][issues.OWNER_MISMATCH]}/action", json={"action": "fix_owner"}, headers=h
        )
        assert r.status_code == 409
        async with maker() as s:
            assert (await s.get(ReconciliationIssue, w["issues"][issues.OWNER_MISMATCH])).status == "open"


async def test_orphans_are_listed_and_can_be_hidden_but_never_deleted():
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        w = await _world(maker, main)
        listed = (await c.get(f"{BASE}/panel-orphans", headers=h)).json()
        assert listed["total"] == 1 and listed["items"][0]["username"] == "rahim" and listed["items"][0]["owner_username"] == "Ajdar"
        r = await c.post(f"{BASE}/panel-orphans/{w['orphan']}/ignore", json={"note": "created by hand"}, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "ignored" and r.json()["note"] == "created by hand"
        assert (await c.get(f"{BASE}/panel-orphans", headers=h)).json()["total"] == 0
        assert (await c.get(f"{BASE}/panel-orphans", params={"status": "all"}, headers=h)).json()["total"] == 1


async def test_panel_list_carries_the_access_review(monkeypatch):
    async with api_client() as (c, maker, main):
        h = await _login(c, maker)
        async with maker() as s:
            s.add(
                Panel(
                    name="owner-panel",
                    kind="pasarguard",
                    base_url="https://o.example.com",
                    capabilities={"flags": {"node_ops": True}, "denied": {}, "role": "owner", "is_owner": True, "source": "probe"},
                    capabilities_checked_at=utcnow() - dt.timedelta(minutes=1),
                )
            )
            await s.commit()
        rows = (await c.get(f"{BASE}/panels", headers=h)).json()
        access = next(p for p in rows if p["name"] == "owner-panel")["capabilities"]["access"]
        assert access["level"] == "owner" and access["warnings"][0]["code"] == "owner_credential"
