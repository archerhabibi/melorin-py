"""Phase 4: outgoing webhook service against real tables (endpoint CRUD, enqueue idempotency, delivery state machine).

The network is never touched: DNS (``socket.getaddrinfo``) and the HTTP client are replaced by fakes, so the
retry/backoff/auto-disable behaviour can be asserted deterministically.
"""

from __future__ import annotations

import socket

import httpx
import pytest
from sqlalchemy import select

from _db import make_store, make_user, open_session
from melorin.core.crypto import decrypt
from melorin.core.errors import AppError
from melorin.domain import webhook as wh
from melorin.kernel.models.webhooks import WebhookDelivery
from melorin.modules.webhooks import service as svc

PUBLIC_IP = "93.184.216.34"
URL = "https://hooks.example.com/melorin"


def _dns(ips):
    def fake(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]

    return fake


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(svc.socket, "getaddrinfo", _dns([PUBLIC_IP]))


class FakeClient:
    """Stand-in for ``httpx.AsyncClient`` recording the request and returning/raising a canned outcome."""

    calls: list = []
    outcome: object = 200

    def __init__(self, *a, **k):
        self.kwargs = k

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, content=None, headers=None):
        FakeClient.calls.append({"url": url, "content": content, "headers": headers, "follow": self.kwargs.get("follow_redirects")})
        if isinstance(FakeClient.outcome, Exception):
            raise FakeClient.outcome
        return httpx.Response(FakeClient.outcome)


@pytest.fixture
def http(monkeypatch):
    FakeClient.calls, FakeClient.outcome = [], 200
    monkeypatch.setattr(svc.httpx, "AsyncClient", FakeClient)
    return FakeClient


async def _endpoint(s, events=("*",), url=URL):
    store = await make_store(s)
    user = await make_user(s)
    e, secret = await svc.create_endpoint(s, store.id, url, list(events), "d", user.id)
    return store, user, e, secret


# --- endpoint management -------------------------------------------------------------------------------------------


async def test_create_endpoint_encrypts_secret_and_returns_it_once():
    async with open_session() as s:
        _, _, e, secret = await _endpoint(s, events=["order.completed", "order.completed"])
        assert e.events == ["order.completed"]
        assert e.secret_enc != secret and decrypt(e.secret_enc) == secret
        assert "secret" not in svc.endpoint_out(e)
        assert svc.endpoint_out(e)["status"] == "active"


async def test_create_endpoint_rejects_unknown_event_and_unsafe_urls(monkeypatch):
    async with open_session() as s:
        store = await make_store(s)
        with pytest.raises(AppError) as bad_event:
            await svc.create_endpoint(s, store.id, URL, ["nope.event"], None, None)
        assert bad_event.value.code == "WEBHOOK_EVENT_INVALID"
        with pytest.raises(AppError) as http_url:
            await svc.create_endpoint(s, store.id, "http://hooks.example.com/x", ["*"], None, None)
        assert http_url.value.code == "WEBHOOK_URL_FORBIDDEN"
        monkeypatch.setattr(svc.socket, "getaddrinfo", _dns(["10.0.0.5"]))
        with pytest.raises(AppError) as private:
            await svc.create_endpoint(s, store.id, URL, ["*"], None, None)
        assert private.value.code == "WEBHOOK_URL_FORBIDDEN"


async def test_unresolvable_host_is_reported_as_invalid(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(svc.socket, "getaddrinfo", boom)
    async with open_session() as s:
        store = await make_store(s)
        with pytest.raises(AppError) as err:
            await svc.create_endpoint(s, store.id, URL, ["*"], None, None)
        assert err.value.code == "WEBHOOK_URL_INVALID"


async def test_get_and_list_endpoints_are_store_scoped():
    async with open_session() as s:
        store, _, e, _ = await _endpoint(s)
        other = await make_store(s)
        assert (await svc.get_endpoint(s, store.id, e.id)).id == e.id
        with pytest.raises(AppError) as nf:
            await svc.get_endpoint(s, other.id, e.id)
        assert nf.value.code == "NOT_FOUND" and nf.value.status == 404
        assert [x.id for x in await svc.list_endpoints(s, store.id)] == [e.id]
        assert await svc.list_endpoints(s, other.id) == []


async def test_update_endpoint_validates_and_reactivation_resets_failures():
    async with open_session() as s:
        _, user, e, _ = await _endpoint(s)
        e.status, e.consecutive_failures = "auto_disabled", 10
        await svc.update_endpoint(s, e, description="new", events=["payment.failed"], status="active", actor_id=user.id)
        assert (e.description, e.events, e.status, e.consecutive_failures) == ("new", ["payment.failed"], "active", 0)
        await svc.update_endpoint(s, e, url="https://other.example.com/h")
        assert e.url == "https://other.example.com/h"
        with pytest.raises(AppError) as err:
            await svc.update_endpoint(s, e, events=["bogus"])
        assert err.value.code == "WEBHOOK_EVENT_INVALID"
        with pytest.raises(AppError):
            await svc.update_endpoint(s, e, url="http://insecure.example.com")


async def test_rotate_secret_keeps_previous_secret_for_dual_signing_window():
    async with open_session() as s:
        _, user, e, old = await _endpoint(s)
        new = await svc.rotate_secret(s, e, user.id)
        assert new != old and decrypt(e.secret_enc) == new
        assert decrypt(e.previous_secret_enc) == old
        assert e.previous_secret_expires_at is not None


# --- enqueue -------------------------------------------------------------------------------------------------------


async def test_enqueue_filters_by_subscription_and_status_and_is_idempotent_on_event_id():
    async with open_session() as s:
        _, _, e, _ = await _endpoint(s, events=["order.completed"])
        assert await svc.enqueue(s, endpoint=e, event_type="payment.failed", payload={}) is None
        first = await svc.enqueue(s, endpoint=e, event_type="order.completed", payload={"n": 1}, event_id="evt-1")
        again = await svc.enqueue(s, endpoint=e, event_type="order.completed", payload={"n": 2}, event_id="evt-1")
        assert first.id == again.id and again.payload == {"n": 1}
        e.status = "disabled"
        assert await svc.enqueue(s, endpoint=e, event_type="order.completed", payload={}, event_id="evt-2") is None


async def test_enqueue_event_fans_out_to_every_active_endpoint_of_the_store_only():
    async with open_session() as s:
        store, user, e1, _ = await _endpoint(s)
        e2, _ = await svc.create_endpoint(s, store.id, "https://b.example.com/h", ["wallet.changed"], None, user.id)
        e3, _ = await svc.create_endpoint(s, store.id, "https://c.example.com/h", ["*"], None, user.id)
        e3.status = "disabled"
        other_store, _, _, _ = await _endpoint(s)
        out = await svc.enqueue_event(s, store_id=store.id, event_type="order.completed", payload={"x": 1}, event_id="e-1")
        assert {d.endpoint_id for d in out} == {e1.id}  # e2 not subscribed, e3 disabled, other store untouched
        assert all(d.store_id == store.id for d in out)
        assert other_store.id != store.id


async def test_enqueue_test_creates_unique_test_events_and_list_deliveries_is_endpoint_scoped():
    async with open_session() as s:
        _, _, e, _ = await _endpoint(s)
        a, b = await svc.enqueue_test(s, e), await svc.enqueue_test(s, e)
        assert a.event_id != b.event_id and a.event_id.startswith("test:")
        assert {d.id for d in await svc.list_deliveries(s, e.id)} == {a.id, b.id}
        assert svc.delivery_out(a)["status"] == "pending"


async def test_redeliver_resets_delivery_and_reactivates_endpoint_but_checks_ownership():
    async with open_session() as s:
        _, user, e, _ = await _endpoint(s)
        d = await svc.enqueue(s, endpoint=e, event_type="order.completed", payload={}, event_id="r-1")
        d.status, d.attempts, d.last_error = "failed", 9, "boom"
        e.status, e.consecutive_failures = "auto_disabled", 10
        await svc.redeliver(s, e, d.id, user.id)
        assert (d.status, d.attempts, d.last_error, e.status, e.consecutive_failures) == ("pending", 0, None, "active", 0)
        _, _, other, _ = await _endpoint(s)
        with pytest.raises(AppError) as nf:
            await svc.redeliver(s, other, d.id, user.id)
        assert nf.value.code == "NOT_FOUND"


# --- deliver_one ---------------------------------------------------------------------------------------------------


async def _pending(s, **kw):
    _, _, e, secret = await _endpoint(s, **kw)
    d = await svc.enqueue(s, endpoint=e, event_type="order.completed", payload={"order": "A1"}, event_id="d-1")
    await s.commit()
    return e, d, secret


async def test_deliver_one_success_signs_body_and_marks_delivered(http):
    async with open_session() as s:
        e, d, secret = await _pending(s)
        e.consecutive_failures = 3
        assert await svc.deliver_one(s, d.id) == "delivered"
        call = http.calls[0]
        assert call["follow"] is False and call["url"] == URL
        h = call["headers"]
        assert h[wh.EVENT_ID_HEADER] == "d-1" and h[wh.EVENT_TYPE_HEADER] == "order.completed"
        assert wh.verify(secret, h[wh.SIGNATURE_HEADER], call["content"])  # receiver can verify what we sent
        assert (d.status, d.attempts, d.last_status_code, d.last_error, e.consecutive_failures) == ("delivered", 1, 200, None, 0)
        assert d.delivered_at is not None


async def test_deliver_one_ignores_finished_missing_and_disabled(http):
    async with open_session() as s:
        e, d, _ = await _pending(s)
        import uuid

        assert await svc.deliver_one(s, uuid.uuid4()) == "ignored"
        e.status = "disabled"
        assert await svc.deliver_one(s, d.id) == "disabled"
        e.status, d.status = "active", "delivered"
        assert await svc.deliver_one(s, d.id) == "ignored"
        assert http.calls == []


async def test_http_error_schedules_retry_with_backoff_and_counts_failure(http):
    http.outcome = 500
    async with open_session() as s:
        e, d, _ = await _pending(s)
        assert await svc.deliver_one(s, d.id) == "pending"
        assert (d.attempts, d.last_status_code, d.last_error, e.consecutive_failures) == (1, 500, "HTTP 500", 1)
        assert d.next_attempt_at > d.created_at


async def test_network_error_is_recorded_without_leaking_exception_type_in_state(http):
    http.outcome = httpx.ConnectError("refused")
    async with open_session() as s:
        e, d, _ = await _pending(s)
        assert await svc.deliver_one(s, d.id) == "pending"
        assert "refused" in d.last_error and d.last_status_code is None


async def test_last_attempt_gives_up_and_ten_failures_auto_disable_the_endpoint(http):
    http.outcome = 503
    async with open_session() as s:
        e, d, _ = await _pending(s)
        d.attempts = wh.MAX_ATTEMPTS - 1  # next attempt is the last one: no more backoff slots
        e.consecutive_failures = 9
        assert await svc.deliver_one(s, d.id) == "failed"
        assert e.status == "auto_disabled" and e.consecutive_failures == 10
        # a failed delivery is terminal until redelivered
        assert await svc.deliver_one(s, d.id) == "ignored"
        row = await s.scalar(select(WebhookDelivery).where(WebhookDelivery.id == d.id))
        assert row.status == "failed"


async def test_dns_rebinding_between_checks_aborts_delivery_before_any_request(http, monkeypatch):
    async with open_session() as s:
        _, d, _ = await _pending(s)
        # 1st/2nd lookups (validation) see the public IP, the 3rd/4th (pre/post) disagree -> the answer changed mid-delivery
        answers = iter([[PUBLIC_IP], [PUBLIC_IP], [PUBLIC_IP], ["93.184.216.35"]])
        monkeypatch.setattr(svc.socket, "getaddrinfo", lambda *a, **k: _dns(next(answers))(*a, **k))
        with pytest.raises(AppError) as err:
            await svc.deliver_one(s, d.id)
        assert err.value.code == "WEBHOOK_DNS_CHANGED" and http.calls == []


async def test_endpoint_resolving_to_private_ip_at_delivery_time_is_refused(http, monkeypatch):
    async with open_session() as s:
        _, d, _ = await _pending(s)
        monkeypatch.setattr(svc.socket, "getaddrinfo", _dns(["127.0.0.1"]))
        with pytest.raises(AppError) as err:
            await svc.deliver_one(s, d.id)
        assert err.value.code == "WEBHOOK_URL_FORBIDDEN" and http.calls == []
