"""PasarGuard Phase 2 (PG-03): live events. Wire format, store-then-process, the public endpoint and the admin connect/disconnect API."""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_order, make_product, make_user, open_schema_engine
from _http import PASSWORD, add_user, api_client, totp_now
from melorin.core.crypto import encrypt
from melorin.core.db import utcnow
from melorin.kernel.models.vpn import Panel, PanelEvent, ReconciliationIssue, VpnAccount
from melorin.modules.vpn import panel_events, panel_events_admin
from melorin.modules.vpn.adapters.base import Capabilities, ErrorKind, PanelAccount, PanelError
from melorin.modules.vpn.adapters.pasarguard import events as wire

SECRET = "s3cret-value-for-tests"
NOW = utcnow()


# ------------------------------------------------------------------------------------------------------------------ wire
def test_secret_check_is_exact_case_insensitive_on_header_name_only():
    assert wire.verify_secret({"X-Webhook-Secret": SECRET}, SECRET)
    assert wire.verify_secret({"x-webhook-secret": SECRET}, SECRET)
    assert not wire.verify_secret({"x-webhook-secret": SECRET.upper()}, SECRET)
    assert not wire.verify_secret({}, SECRET)
    assert not wire.verify_secret({"x-webhook-secret": SECRET}, None)  # a panel never connected accepts nothing
    assert not wire.verify_secret({"x-webhook-secret": ""}, "")


def test_parse_accepts_list_single_object_and_wrapped_events():
    one = {"action": "user_limited", "username": "alice", "enqueued_at": 1_700_000_000, "tries": 0}
    assert len(wire.parse_body(json.dumps([one, one | {"username": "bob"}]).encode()).events) == 2
    assert len(wire.parse_body(json.dumps(one).encode()).events) == 1
    assert len(wire.parse_body(json.dumps({"events": [one]}).encode()).events) == 1


def test_parse_rejects_non_json_but_skips_bad_items_without_failing_the_delivery():
    with pytest.raises(ValueError):
        wire.parse_body(b"<html>")
    with pytest.raises(ValueError):
        wire.parse_body(json.dumps("just a string").encode())
    parsed = wire.parse_body(
        json.dumps([{"action": "user_expired", "username": "a"}, 5, {"action": "Bad Action!"}, {"nothing": 1}]).encode()
    )
    assert [e.action for e in parsed.events] == ["user_expired"] and parsed.rejected == 3


def test_dedup_key_prefers_the_panels_own_id_and_is_stable_without_it():
    with_id = wire.parse_body(json.dumps([{"id": "evt-1", "action": "user_updated", "username": "a", "enqueued_at": 1}]).encode()).events[0]
    again = wire.parse_body(json.dumps([{"id": "evt-1", "action": "user_updated", "username": "a", "enqueued_at": 99}]).encode()).events[0]
    assert with_id.dedup_key == again.dedup_key == "id:evt-1"
    plain = {"action": "user_updated", "username": "a", "enqueued_at": 1_700_000_000}
    k1 = wire.parse_body(json.dumps([plain]).encode()).events[0].dedup_key
    k2 = wire.parse_body(json.dumps([plain]).encode()).events[0].dedup_key
    k3 = wire.parse_body(json.dumps([plain | {"enqueued_at": 1_700_000_001}]).encode()).events[0].dedup_key
    assert k1 == k2 != k3


def test_stored_payload_never_keeps_links_or_proxy_settings():
    raw = {
        "action": "user_updated",
        "username": "a",
        "by": {"username": "root", "password": "x"},
        "user": {
            "status": "active",
            "subscription_url": "https://sub/abc",
            "proxy_settings": {"vless": {"id": "u"}},
            "admin": {"username": "ml_main", "token": "t"},
        },
    }
    text = json.dumps(wire.sanitize(raw))
    for leak in ("subscription_url", "proxy_settings", "https://sub", "password", "token"):
        assert leak not in text
    assert wire.sanitize(raw)["user"]["admin"] == "ml_main"


def test_non_finite_numbers_never_reach_the_stored_payload_or_fail_the_delivery():
    body = (
        b'[{"action":"user_updated","username":"a","tries":Infinity,"reset_traffic":NaN,"user":{"used_traffic":1e999,"status":"active"}},'
        b'{"action":"user_limited","username":"b","tries":1e30}]'
    )
    parsed = wire.parse_body(body)  # used to raise OverflowError -> 500 -> the panel retried the same delivery forever
    assert [e.action for e in parsed.events] == ["user_updated", "user_limited"] and parsed.rejected == 0
    assert parsed.events[0].tries == 0 and parsed.events[1].tries == wire.MAX_TRIES
    json.dumps(parsed.events[0].payload, allow_nan=False)  # what PostgreSQL's JSON type accepts
    assert parsed.events[0].payload["user"] == {"status": "active"}


def test_one_unusable_item_never_fails_the_rest(monkeypatch):
    real = wire._parse_item

    def boom(item, now):
        if item.get("username") == "bad":
            raise RuntimeError("poison")
        return real(item, now)

    monkeypatch.setattr(wire, "_parse_item", boom)
    parsed = wire.parse_body(
        json.dumps([{"action": "user_updated", "username": "bad"}, {"action": "user_updated", "username": "ok"}]).encode()
    )
    assert [e.username for e in parsed.events] == ["ok"] and parsed.rejected == 1


def test_events_without_id_and_timestamp_are_not_swallowed_forever():
    ev = json.dumps([{"action": "user_limited", "username": "a"}]).encode()
    t0 = dt.datetime(2026, 11, 7, 10, 0, 5, tzinfo=dt.UTC)
    same_minute = (
        wire.parse_body(ev, now=t0).events[0].dedup_key == wire.parse_body(ev, now=t0 + dt.timedelta(seconds=40)).events[0].dedup_key
    )
    later = wire.parse_body(ev, now=t0 + dt.timedelta(days=2)).events[0].dedup_key
    assert same_minute  # an immediate re-delivery of the same body is still a duplicate
    assert later != wire.parse_body(ev, now=t0).events[0].dedup_key  # a genuinely new event days later is a new event
    other = json.dumps([{"action": "user_limited", "username": "a", "reason": "x"}]).encode()
    assert wire.parse_body(other, now=t0).events[0].dedup_key != wire.parse_body(ev, now=t0).events[0].dedup_key


class _Settings:
    """Just enough of the adapter to run the webhook mixin against an in-memory ``/api/settings``."""

    def __init__(self, settings):
        self.settings, self.writes = settings, 0

    async def get_settings(self):
        return json.loads(json.dumps(self.settings))

    async def _put_settings(self, new):
        self.writes += 1
        self.settings = json.loads(json.dumps(new))
        return self.settings


class _Mixin(_Settings, wire.EventsMixin):
    _others = staticmethod(wire.EventsMixin._others)


URL = "https://m.example.com/api/v1/webhooks/pasarguard/p"


async def test_connect_keeps_other_targets_and_settings_and_is_idempotent():
    a = _Mixin({"general": {"x": 1}, "webhook": {"enable": False, "webhooks": [{"url": "https://other", "secret": "o"}], "days_left": [7]}})
    r = await a.connect_webhook(URL, "k")
    assert r["enabled"] and r["melorin_registered"] and r["other_targets"] == 1 and not r["warnings"]
    assert a.settings["general"] == {"x": 1} and a.settings["webhook"]["days_left"] == [7]  # an admin's threshold is never overwritten
    assert a.settings["webhook"]["usage_percent"] == list(wire.DEFAULT_USAGE_PERCENT)  # only empty ones are filled
    await a.connect_webhook(URL, "k2")
    assert [e["url"] for e in a.settings["webhook"]["webhooks"]].count(URL) == 1  # replaced, never duplicated
    assert next(e for e in a.settings["webhook"]["webhooks"] if e["url"] == URL)["secret"] == "k2"


async def test_disconnect_removes_only_melorin_and_keeps_the_webhook_on_for_others():
    a = _Mixin({"webhook": {"enable": True, "webhooks": [{"url": "https://other", "secret": "o"}, {"url": URL, "secret": "k"}]}})
    r = await a.disconnect_webhook(URL)
    assert not r["melorin_registered"] and a.settings["webhook"]["enable"] is True and len(a.settings["webhook"]["webhooks"]) == 1
    r = await _Mixin({"webhook": {"enable": True, "webhooks": [{"url": URL, "secret": "k"}]}}).disconnect_webhook(URL)
    assert r["enabled"] is False


async def test_connect_fails_loudly_when_the_panel_does_not_keep_the_setting():
    class Forgetful(_Mixin):
        async def _put_settings(self, new):
            return self.settings  # accepted but ignored

    with pytest.raises(PanelError):
        await Forgetful({"webhook": {"enable": False}}).connect_webhook(URL, "k")


# ------------------------------------------------------------------------------------------------------- store then process
@pytest.fixture
async def maker():
    async with open_schema_engine() as engine:
        yield async_sessionmaker(engine, expire_on_commit=False)


class FakePanel:
    def __init__(self, users=(), fail=False):
        self.users, self.fail, self.reads = {u.username: u for u in users}, fail, 0

    def capabilities(self):
        return Capabilities(account_listing=True)

    async def get_account(self, username):
        self.reads += 1
        if self.fail:
            raise PanelError(ErrorKind.TRANSIENT, "panel down")
        return self.users.get(username)

    async def close(self):
        return None


def remote(username, *, status="active", ref="1"):
    return PanelAccount(
        ref=ref,
        username=username,
        status=status,
        expire_at=NOW + dt.timedelta(days=30),
        traffic_limit_bytes=10 * 2**30,
        traffic_used_bytes=10 * 2**30 if status == "limited" else 0,
        remote_status=status,
        owner="ml_main",
    )


async def _world(maker, *, connected=True, username="alice"):
    async with maker() as s:
        user, product = await make_user(s), await make_product(s)
        from _db import make_store

        store = await make_store(s, kind="main")
        order = await make_order(s, user=user, store=store, product=product)
        panel = Panel(name="pg", kind="pasarguard", base_url="https://p.example.com", health_status="healthy")
        if connected:
            panel.webhook_secret_enc, panel.webhook_connected_at = encrypt(SECRET), NOW
        s.add(panel)
        await s.flush()
        s.add(
            VpnAccount(
                username=username,
                user_id=user.id,
                store_id=store.id,
                order_id=order.id,
                product_id=product.id,
                panel_id=panel.id,
                panel_ref="1",
                status="active",
            )
        )
        await s.commit()
        return panel.id


def _body(*events):
    return json.dumps(list(events)).encode()


def _ev(action, username="alice", at=None, **extra):
    return {"action": action, "username": username, "enqueued_at": (at or NOW).timestamp(), "tries": 0, **extra}


async def _ingest(maker, panel_id, body, *, now=None):
    async with maker() as s:
        panel = await s.get(Panel, panel_id)
        return await panel_events.ingest(s, panel, wire.parse_body(body), now=now)


async def test_replayed_delivery_is_stored_once_and_counted_as_duplicate(maker):
    pid = await _world(maker)
    body = _body(_ev("user_limited"), _ev("user_limited", username="bob"))
    first = await _ingest(maker, pid, body)
    again = await _ingest(maker, pid, body)
    assert (first.accepted, first.duplicates) == (2, 0) and (again.accepted, again.duplicates) == (0, 2)
    async with maker() as s:
        assert await s.scalar(select(func.count()).select_from(PanelEvent)) == 2
        assert (await s.get(Panel, pid)).webhook_last_at is not None


async def test_duplicate_inside_one_delivery_and_unknown_or_stale_events_are_not_queued(maker):
    pid = await _world(maker)
    old = NOW - panel_events.MAX_AGE - dt.timedelta(days=1)
    r = await _ingest(
        maker,
        pid,
        _body(_ev("user_updated"), _ev("user_updated"), _ev("something_new"), _ev("user_limited", at=old), {"action": "user_limited"}),
    )
    assert (r.accepted, r.duplicates, r.ignored) == (1, 1, 3)
    async with maker() as s:
        outcomes = {e.action: e.outcome for e in (await s.scalars(select(PanelEvent).where(PanelEvent.status == "ignored"))).all()}
    assert outcomes["something_new"] == "unknown_action" and outcomes["user_limited"] in ("stale", "no_username")


async def test_several_events_for_one_user_cost_one_panel_read_and_the_status_follows_the_panel(maker, monkeypatch):
    pid = await _world(maker)
    fake = FakePanel([remote("alice", status="limited")])
    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: fake)
    await _ingest(maker, pid, _body(_ev("user_updated", id="1"), _ev("user_limited", id="2"), _ev("reached_usage_percent", id="3")))
    stats = await panel_events.run_pending(factory=maker)
    assert (stats.claimed, stats.processed) == (3, 3) and fake.reads == 1  # coalesced
    async with maker() as s:
        assert (await s.scalar(select(VpnAccount.status).where(VpnAccount.username == "alice"))) == "limited"
        rows = (await s.scalars(select(PanelEvent))).all()
        assert {r.status for r in rows} == {"processed"} and all(r.vpn_account_id for r in rows)
    again = await panel_events.run_pending(factory=maker)
    assert again.claimed == 0  # nothing is processed twice


async def test_the_payload_is_never_trusted_as_state(maker, monkeypatch):
    """A forged-but-authenticated event claiming ``expired`` changes nothing when the panel says the user is active."""
    pid = await _world(maker)
    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: FakePanel([remote("alice", status="active")]))
    await _ingest(maker, pid, _body(_ev("user_expired", user={"status": "expired"})))
    await panel_events.run_pending(factory=maker)
    async with maker() as s:
        assert (await s.scalar(select(VpnAccount.status).where(VpnAccount.username == "alice"))) == "active"


async def test_user_deleted_opens_a_missing_issue_and_deletes_nothing(maker, monkeypatch):
    pid = await _world(maker)
    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: FakePanel([]))
    await _ingest(maker, pid, _body(_ev("user_deleted")))
    await panel_events.run_pending(factory=maker)
    async with maker() as s:
        acc = (await s.scalars(select(VpnAccount))).one()
        assert acc.status == "active" and acc.archived_at is None
        issue = (await s.scalars(select(ReconciliationIssue))).one()
        assert (issue.kind, issue.status) == ("missing_on_panel", "open")
        assert (await s.scalar(select(PanelEvent.outcome))) == "missing_on_panel"


async def test_unknown_user_is_retried_briefly_then_left_to_reconcile(maker, monkeypatch):
    pid = await _world(maker)
    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: FakePanel([remote("ghost")]))
    await _ingest(maker, pid, _body(_ev("user_created", username="ghost")))
    t = utcnow()
    for i in range(panel_events.UNKNOWN_ACCOUNT_RETRIES + 1):
        await panel_events.run_pending(factory=maker, now=t + dt.timedelta(minutes=10 * (i + 1)))
    async with maker() as s:
        row = (await s.scalars(select(PanelEvent))).one()
        assert row.status == "ignored" and "unknown_account" in row.outcome


async def test_panel_outage_keeps_retrying_for_hours_then_gives_up_and_admin_can_requeue(maker, monkeypatch):
    pid = await _world(maker)
    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: FakePanel([remote("alice")], fail=True))
    await _ingest(maker, pid, _body(_ev("user_limited")))
    t = utcnow()
    for i in range(panel_events.MAX_ATTEMPTS):  # the old limit: a short outage must NOT use the event up
        await panel_events.run_pending(factory=maker, now=t + dt.timedelta(hours=i + 1))
    async with maker() as s:
        row = (await s.scalars(select(PanelEvent))).one()
        assert row.status == "pending" and row.attempts == panel_events.MAX_ATTEMPTS
    for i in range(panel_events.MAX_ATTEMPTS, panel_events.PANEL_MAX_ATTEMPTS):
        await panel_events.run_pending(factory=maker, now=t + dt.timedelta(hours=i + 1))
    async with maker() as s:
        row = (await s.scalars(select(PanelEvent))).one()
        assert row.status == "failed" and row.attempts == panel_events.PANEL_MAX_ATTEMPTS
        assert await panel_events_admin.retry_failed(s, pid) == 1
        await s.commit()
    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: FakePanel([remote("alice", status="limited")]))
    await panel_events.run_pending(factory=maker, now=t + dt.timedelta(hours=40))
    async with maker() as s:
        assert (await s.scalar(select(PanelEvent.status))) == "processed"
        assert (await s.scalar(select(VpnAccount.status))) == "limited"


async def test_a_permanent_panel_error_needs_a_person_and_fails_after_the_short_limit(maker, monkeypatch):
    pid = await _world(maker)

    class Forbidden(FakePanel):
        async def get_account(self, username):
            raise PanelError(ErrorKind.PERMANENT, "forbidden")

    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: Forbidden())
    await _ingest(maker, pid, _body(_ev("user_limited")))
    t = utcnow()
    for i in range(panel_events.MAX_ATTEMPTS):
        await panel_events.run_pending(factory=maker, now=t + dt.timedelta(hours=i + 1))
    async with maker() as s:
        assert (await s.scalar(select(PanelEvent.status))) == "failed"


async def test_a_renewal_that_commits_while_the_panel_is_read_forces_a_second_read_under_the_lock(maker, monkeypatch):
    """The panel is read without the row lock; an account that changed meanwhile must not be overwritten by the older panel answer."""
    pid = await _world(maker)

    class Racing(FakePanel):
        async def get_account(self, username):
            self.reads += 1
            if self.reads == 1:
                async with maker() as other:  # a renewal commits while we are talking to the panel
                    acc = (await other.scalars(select(VpnAccount))).one()
                    acc.sync_error_count = 99
                    await other.commit()
                return remote(username, status="active")  # the OLD state
            return remote(username, status="limited")  # what the panel says after the renewal

    fake = Racing()
    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: fake)
    await _ingest(maker, pid, _body(_ev("user_limited")))
    await panel_events.run_pending(factory=maker)
    assert fake.reads == 2
    async with maker() as s:
        assert (await s.scalar(select(VpnAccount.status))) == "limited"


async def test_an_abandoned_lease_is_released_and_a_disabled_panel_is_ignored(maker, monkeypatch):
    pid = await _world(maker)
    monkeypatch.setattr(panel_events, "build_adapter", lambda panel: FakePanel([remote("alice", status="limited")]))
    await _ingest(maker, pid, _body(_ev("user_limited")))
    async with maker() as s:  # a worker claimed it and died long ago
        row = (await s.scalars(select(PanelEvent))).one()
        row.status, row.available_at = "processing", utcnow() - dt.timedelta(minutes=1)
        await s.commit()
    assert (await panel_events.run_pending(factory=maker)).processed == 1
    await _ingest(maker, pid, _body(_ev("user_updated", username="alice", at=NOW + dt.timedelta(seconds=5))))
    async with maker() as s:
        (await s.get(Panel, pid)).is_enabled = False
        await s.commit()
    await panel_events.run_pending(factory=maker)
    async with maker() as s:
        last = (await s.scalars(select(PanelEvent).order_by(PanelEvent.received_at.desc()))).first()
        assert last.status == "ignored" and last.outcome == "panel_disabled"


async def test_retention_removes_only_finished_old_events(maker):
    pid = await _world(maker)
    old = NOW - panel_events.RETENTION - dt.timedelta(days=1)
    async with maker() as s:
        for i, st in enumerate(("processed", "failed", "pending", "ignored")):
            s.add(PanelEvent(panel_id=pid, dedup_key=f"k{i}", action="user_updated", username="a", received_at=old, status=st))
        s.add(PanelEvent(panel_id=pid, dedup_key="fresh", action="user_updated", username="a", received_at=NOW, status="processed"))
        await s.commit()
        assert await panel_events.purge(s) == 3
        left = set((await s.scalars(select(PanelEvent.dedup_key))).all())
    assert left == {"k2", "fresh"}  # the old pending one is still work to do


# -------------------------------------------------------------------------------------------------------- public endpoint
def _url(pid):
    return f"/api/v1/webhooks/pasarguard/{pid}"


async def test_endpoint_accepts_a_good_delivery_and_dedups_a_retry():
    async with api_client() as (c, maker, _):
        pid = await _world(maker)
        h = {"x-webhook-secret": SECRET, "content-type": "application/json"}
        body = _body(_ev("user_limited", id="e1"))
        r = await c.post(_url(pid), content=body, headers=h)
        assert r.status_code == 200 and r.json()["accepted"] == 1
        r = await c.post(_url(pid), content=body, headers=h)
        assert r.status_code == 200 and r.json() == {"ok": True, "accepted": 0, "duplicates": 1, "ignored": 0, "rejected": 0}


async def test_endpoint_answers_wrong_secret_unknown_panel_and_unconnected_panel_identically():
    import uuid

    async with api_client() as (c, maker, _):
        pid = await _world(maker)
        free = await _world(maker, connected=False, username="zed")
        body = _body(_ev("user_limited"))
        answers = [
            await c.post(_url(pid), content=body, headers={"x-webhook-secret": "wrong"}),
            await c.post(_url(uuid.uuid4()), content=body, headers={"x-webhook-secret": SECRET}),
            await c.post(_url(free), content=body, headers={"x-webhook-secret": SECRET}),
            await c.post(_url(pid), content=body),
        ]
        assert {a.status_code for a in answers} == {401} and len(
            {(a.json()["error"]["code"], a.json()["error"]["message"]) for a in answers}
        ) == 1  # no panel enumeration
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(PanelEvent)) == 0


async def test_endpoint_rejects_oversized_and_non_json_bodies_and_throttles_wrong_secrets():
    async with api_client() as (c, maker, _):
        pid = await _world(maker)
        ok = {"x-webhook-secret": SECRET}
        assert (await c.post(_url(pid), content=b"x" * (wire.MAX_BODY_BYTES + 1), headers=ok)).status_code == 413
        assert (await c.post(_url(pid), content=b"not json", headers=ok)).status_code == 400
        codes = [(await c.post(_url(pid), content=b"[]", headers={"x-webhook-secret": f"bad{i}"})).status_code for i in range(12)]
        assert codes[:10] == [401] * 10 and 429 in codes[10:]


# ----------------------------------------------------------------------------------------------------------- admin connect
class FakeAdminAdapter:
    def __init__(self, ok=True):
        self.ok, self.calls, self.registered = ok, [], False

    def capabilities(self):
        return Capabilities(event_source=True)

    def verify_webhook(self, headers, body, secret):
        return wire.verify_secret(headers, secret)

    async def connect_webhook(self, url, secret):
        self.calls.append(("connect", url, secret))
        if not self.ok:
            raise PanelError(ErrorKind.PERMANENT, "forbidden")
        self.registered = True
        return {
            "enabled": True,
            "targets": 1,
            "melorin_registered": True,
            "other_targets": 0,
            "days_left": [3],
            "usage_percent": [80, 90],
            "warnings": [],
        }

    async def disconnect_webhook(self, url):
        self.calls.append(("disconnect", url))
        self.registered = False
        return {
            "enabled": False,
            "targets": 0,
            "melorin_registered": False,
            "other_targets": 0,
            "days_left": [],
            "usage_percent": [],
            "warnings": [],
        }

    async def get_webhook_config(self, url):
        return {
            "enabled": self.registered,
            "targets": int(self.registered),
            "melorin_registered": self.registered,
            "other_targets": 0,
            "days_left": [],
            "usage_percent": [],
        }

    async def close(self):
        return None


async def _admin(c, maker):
    await add_user(maker, email="root@example.com", admin=True, totp=True)
    r = await c.post("/api/v1/auth/password/login", json={"email": "root@example.com", "password": PASSWORD, "totp_code": totp_now()})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def public_url(monkeypatch):
    monkeypatch.setattr(panel_events_admin, "get_settings", lambda: SimpleNamespace(public_api_url="https://m.example.com"))


async def test_connect_needs_confirmation_stores_the_secret_encrypted_and_never_returns_it(public_url, monkeypatch):
    fake = FakeAdminAdapter()
    monkeypatch.setattr(panel_events_admin, "build_adapter", lambda panel: fake)
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        pid = await _world(maker, connected=False)
        base = f"/api/v1/admin/panels/{pid}/events"
        assert (await c.post(f"{base}/connect", json={"confirm": False}, headers=h)).status_code == 422
        assert fake.calls == []  # nothing was written to the panel
        r = await c.post(f"{base}/connect", json={"confirm": True}, headers=h)
        assert r.status_code == 200, r.text
        secret = fake.calls[0][2]
        assert len(secret) >= 32 and secret not in r.text and r.json()["connected"] is True
        assert r.json()["url"] == f"https://m.example.com/api/v1/webhooks/pasarguard/{pid}"
        async with maker() as s:
            p = await s.get(Panel, pid)
            assert p.webhook_secret_enc and secret not in p.webhook_secret_enc and panel_events.secret_for(p) == secret
        # the secret Melorin stored is the one the endpoint now accepts
        assert (
            await c.post(f"/api/v1/webhooks/pasarguard/{pid}", content=_body(_ev("user_updated")), headers={"x-webhook-secret": secret})
        ).status_code == 200
        # connecting again keeps the same secret; rotating replaces it
        await c.post(f"{base}/connect", json={"confirm": True}, headers=h)
        assert fake.calls[1][2] == secret
        await c.post(f"{base}/connect", json={"confirm": True, "rotate_secret": True}, headers=h)
        assert fake.calls[2][2] != secret
        assert (
            await c.post(f"/api/v1/webhooks/pasarguard/{pid}", content=_body(_ev("user_updated")), headers={"x-webhook-secret": secret})
        ).status_code == 401


async def test_a_refused_connect_restores_the_previous_state(public_url, monkeypatch):
    monkeypatch.setattr(panel_events_admin, "build_adapter", lambda panel: FakeAdminAdapter(ok=False))
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        pid = await _world(maker, connected=False)
        r = await c.post(f"/api/v1/admin/panels/{pid}/events/connect", json={"confirm": True}, headers=h)
        assert r.status_code == 502
        async with maker() as s:
            p = await s.get(Panel, pid)
            assert p.webhook_secret_enc is None and p.webhook_connected_at is None


async def test_disconnect_forgets_the_secret_and_status_reports_counts(public_url, monkeypatch):
    fake = FakeAdminAdapter()
    monkeypatch.setattr(panel_events_admin, "build_adapter", lambda panel: fake)
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        pid = await _world(maker)
        base = f"/api/v1/admin/panels/{pid}/events"
        await _ingest(maker, pid, _body(_ev("user_limited")))
        st = (await c.get(f"{base}/status?live=true", headers=h)).json()
        assert st["connected"] and st["counts"]["pending"] == 1 and st["counts"]["last_24h"] == 1 and "secret" not in json.dumps(st)
        assert (await c.post(f"{base}/disconnect", headers=h)).json()["connected"] is False
        assert (
            await c.post(f"/api/v1/webhooks/pasarguard/{pid}", content=_body(_ev("user_updated")), headers={"x-webhook-secret": SECRET})
        ).status_code == 401
        listed = (await c.get(f"{base}?status=pending", headers=h)).json()
        assert listed["total"] == 1 and listed["items"][0]["action"] == "user_limited"
        assert (await c.get(f"{base}?status=bogus", headers=h)).status_code == 422


async def test_event_admin_routes_need_an_admin(public_url):
    async with api_client() as (c, maker, _):
        pid = await _world(maker)
        base = f"/api/v1/admin/panels/{pid}/events"
        assert (await c.get(f"{base}/status")).status_code in (401, 403)
        assert (await c.post(f"{base}/connect", json={"confirm": True})).status_code in (401, 403)


async def test_the_new_secret_is_committed_before_the_panel_is_asked_to_use_it(public_url, monkeypatch):
    seen = {}

    class Spy(FakeAdminAdapter):
        async def connect_webhook(self, url, secret):
            async with maker() as other:  # the public endpoint reads in a different session
                seen["stored"] = panel_events.secret_for(await other.get(Panel, pid))
            return await super().connect_webhook(url, secret)

    monkeypatch.setattr(panel_events_admin, "build_adapter", lambda panel: Spy())
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        pid = await _world(maker, connected=False)
        r = await c.post(f"/api/v1/admin/panels/{pid}/events/connect", json={"confirm": True}, headers=h)
        assert r.status_code == 200, r.text
        assert seen["stored"] and seen["stored"] != SECRET


class _Flaky(FakeAdminAdapter):
    """connect_webhook times out (outcome unknown) ``fail_times`` times, then works; ``applied`` = the panel kept the write anyway."""

    def __init__(self, fail_times, applied=False, exc=None):
        super().__init__()
        self.fail_times, self.applied, self.exc = fail_times, applied, exc

    async def connect_webhook(self, url, secret):
        if self.exc:
            raise self.exc
        if self.fail_times > 0:
            self.fail_times -= 1
            self.registered = self.applied
            self.calls.append(("timeout", url, secret))
            raise PanelError(ErrorKind.UNKNOWN, "pasarguard timeout")
        return await super().connect_webhook(url, secret)


async def _connect(monkeypatch, adapter, *, connected=False):
    monkeypatch.setattr(panel_events_admin, "build_adapter", lambda panel: adapter)
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        pid = await _world(maker, connected=connected)
        r = await c.post(f"/api/v1/admin/panels/{pid}/events/connect", json={"confirm": True, "rotate_secret": True}, headers=h)
        async with maker() as s:
            p = await s.get(Panel, pid)
            return r, panel_events.secret_for(p), p.webhook_connected_at


async def test_a_timeout_on_connect_is_repeated_and_keeps_the_new_secret(public_url, monkeypatch):
    fake = _Flaky(fail_times=1)
    r, stored, connected_at = await _connect(monkeypatch, fake)
    assert r.status_code == 200 and connected_at is not None
    assert stored == fake.calls[-1][2] and stored not in r.text  # the secret the panel finally got is the one Melorin stored


async def test_an_unconfirmed_connect_keeps_the_new_secret_when_the_panel_shows_it_registered(public_url, monkeypatch):
    fake = _Flaky(fail_times=5, applied=True)  # the writes timed out but the panel did apply them
    r, stored, connected_at = await _connect(monkeypatch, fake)
    assert r.status_code == 200 and connected_at is not None and stored == fake.calls[-1][2]
    assert any("قطعی نبود" in w for w in r.json()["warnings"])  # the admin is told, not left guessing


async def test_an_unconfirmed_connect_restores_the_old_state_when_the_panel_did_not_keep_it(public_url, monkeypatch):
    r, stored, connected_at = await _connect(monkeypatch, _Flaky(fail_times=5, applied=False))
    assert r.status_code == 502 and stored is None and connected_at is None


async def test_an_unexpected_error_during_connect_does_not_leave_an_unused_secret(public_url, monkeypatch):
    monkeypatch.setattr(panel_events_admin, "build_adapter", lambda panel: _Flaky(0, exc=RuntimeError("boom")))
    async with api_client() as (c, maker, _):
        h = await _admin(c, maker)
        pid = await _world(maker, connected=False)
        with pytest.raises(RuntimeError):
            await c.post(f"/api/v1/admin/panels/{pid}/events/connect", json={"confirm": True}, headers=h)
        async with maker() as s:
            assert (await s.get(Panel, pid)).webhook_secret_enc is None
