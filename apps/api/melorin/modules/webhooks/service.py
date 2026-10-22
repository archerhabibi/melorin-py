import logging
import secrets
import socket
import time
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.crypto import decrypt, encrypt
from melorin.core.db import utcnow
from melorin.core.errors import AppError, NotFound
from melorin.domain import webhook as wh
from melorin.kernel.models.webhooks import WebhookDelivery, WebhookEndpoint

log = logging.getLogger("melorin.webhooks")


def endpoint_out(e):
    return {
        "id": e.id,
        "url": e.url,
        "description": e.description,
        "events": e.events,
        "status": e.status,
        "consecutive_failures": e.consecutive_failures,
        "created_at": e.created_at,
    }


def delivery_out(d):
    return {
        "id": d.id,
        "event_id": d.event_id,
        "event_type": d.event_type,
        "status": d.status,
        "attempts": d.attempts,
        "last_status_code": d.last_status_code,
        "last_error": d.last_error,
        "last_response_ms": d.last_response_ms,
        "next_attempt_at": d.next_attempt_at,
        "delivered_at": d.delivered_at,
    }


async def _safe(url: str):
    try:
        host = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url).hostname
        ips = [x[4][0] for x in socket.getaddrinfo(host, None)] if host else []
        return wh.check_url(url, resolved_ips=ips)
    except wh.WebhookUrlError as e:
        raise AppError("WEBHOOK_URL_FORBIDDEN", "آدرس وبهوک امن نیست.", 400) from e
    except (socket.gaierror, ValueError) as e:
        raise AppError("WEBHOOK_URL_INVALID", "دامنه وبهوک قابل resolve نیست.", 400) from e


async def create_endpoint(session: AsyncSession, store_id, url, events, description, actor_id):
    await _safe(url)
    invalid = set(events) - set(wh.SUPPORTED_EVENTS) - {"*"}
    if invalid:
        raise AppError("WEBHOOK_EVENT_INVALID", "رویداد وبهوک پشتیبانی نمی‌شود.", 400, {"events": sorted(invalid)})
    secret = secrets.token_urlsafe(32)
    e = WebhookEndpoint(
        store_id=store_id, url=url, description=description, events=sorted(set(events)), secret_enc=encrypt(secret), created_by=actor_id
    )
    session.add(e)
    audit.record(
        session,
        "webhook.created",
        actor_id=actor_id,
        actor_type="reseller",
        entity_type="webhook_endpoint",
        entity_id=e.id,
        store_id=store_id,
    )
    await session.commit()
    return e, secret


async def list_endpoints(session, store_id):
    return (
        await session.scalars(
            select(WebhookEndpoint).where(WebhookEndpoint.store_id == store_id).order_by(WebhookEndpoint.created_at.desc())
        )
    ).all()


async def get_endpoint(session, store_id, endpoint_id):
    e = await session.get(WebhookEndpoint, endpoint_id)
    if not e or e.store_id != store_id:
        raise NotFound("وبهوک")
    return e


async def update_endpoint(session, e, *, url=None, events=None, description=None, status=None, actor_id=None):
    if url:
        await _safe(url)
        e.url = url
    if events is not None:
        invalid = set(events) - set(wh.SUPPORTED_EVENTS) - {"*"}
        if invalid:
            raise AppError("WEBHOOK_EVENT_INVALID", "رویداد وبهوک پشتیبانی نمی‌شود.", 400)
        e.events = sorted(set(events))
    if description is not None:
        e.description = description
    if status is not None:
        e.status = status
        if status == "active":
            e.consecutive_failures = 0
    audit.record(
        session,
        "webhook.updated",
        actor_id=actor_id,
        actor_type="reseller",
        entity_type="webhook_endpoint",
        entity_id=e.id,
        store_id=e.store_id,
    )
    await session.commit()
    return e


async def rotate_secret(session, e, actor_id):
    old = decrypt(e.secret_enc)
    secret = secrets.token_urlsafe(32)
    e.previous_secret_enc = encrypt(old)
    e.previous_secret_expires_at = utcnow() + __import__("datetime").timedelta(hours=24)
    e.secret_enc = encrypt(secret)
    audit.record(
        session,
        "webhook.secret_rotated",
        actor_id=actor_id,
        actor_type="reseller",
        entity_type="webhook_endpoint",
        entity_id=e.id,
        store_id=e.store_id,
    )
    await session.commit()
    return secret


async def enqueue(session, *, endpoint: WebhookEndpoint, event_type: str, payload: dict, event_id: str | None = None):
    if not wh.subscribed(endpoint.events, event_type) or endpoint.status != "active":
        return None
    stable_id = event_id or str(uuid.uuid4())
    existing = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id, WebhookDelivery.event_id == stable_id)
    )
    if existing:
        return existing
    d = WebhookDelivery(endpoint_id=endpoint.id, store_id=endpoint.store_id, event_id=stable_id, event_type=event_type, payload=payload)
    try:
        async with session.begin_nested():
            session.add(d)
            await session.flush()
    except IntegrityError:
        return await session.scalar(
            select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id, WebhookDelivery.event_id == stable_id)
        )
    return d


async def enqueue_event(session, *, store_id, event_type, payload, event_id=None):
    eps = await session.scalars(select(WebhookEndpoint).where(WebhookEndpoint.store_id == store_id, WebhookEndpoint.status == "active"))
    out = []
    for e in eps:
        d = await enqueue(session, endpoint=e, event_type=event_type, payload=payload, event_id=event_id)
        if d:
            out.append(d)
    return out


async def enqueue_test(session, e):
    d = await enqueue(
        session,
        endpoint=e,
        event_type="order.completed",
        payload={"type": "test", "store_id": str(e.store_id), "sent_at": utcnow().isoformat()},
        event_id=f"test:{uuid.uuid4()}",
    )
    await session.commit()
    return d


async def list_deliveries(session, endpoint_id):
    return (
        await session.scalars(
            select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint_id).order_by(WebhookDelivery.created_at.desc()).limit(500)
        )
    ).all()


async def redeliver(session, e, delivery_id, actor_id):
    d = await session.get(WebhookDelivery, delivery_id)
    if not d or d.endpoint_id != e.id:
        raise NotFound("تحویل وبهوک")
    d.status, d.attempts, d.next_attempt_at, d.last_error = "pending", 0, utcnow(), None
    e.status, e.consecutive_failures = "active", 0
    audit.record(
        session,
        "webhook.redelivery_requested",
        actor_id=actor_id,
        actor_type="reseller",
        entity_type="webhook_delivery",
        entity_id=d.id,
        store_id=e.store_id,
    )
    await session.commit()


async def deliver_one(session: AsyncSession, delivery_id):
    d = await session.get(WebhookDelivery, delivery_id, with_for_update=True)
    if not d or d.status in ("delivered", "failed"):
        return "ignored"
    e = await session.get(WebhookEndpoint, d.endpoint_id)
    if not e or e.status != "active":
        return "disabled"
    # Resolve immediately before opening the connection and reject DNS changes
    # between validation and delivery. Redirects stay disabled.
    validated = await _safe(e.url)
    host = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(validated).hostname
    ips_before = {x[4][0] for x in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)} if host else set()
    await _safe(e.url)
    ips_after = {x[4][0] for x in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)} if host else set()
    if not ips_before or ips_before != ips_after:
        raise AppError("WEBHOOK_DNS_CHANGED", "آدرس وبهوک هنگام ارسال تغییر کرده است.", 409)
    d.status, d.attempts = "delivering", d.attempts + 1
    await session.commit()
    body = wh.canonical_body({"id": d.event_id, "type": d.event_type, "created_at": d.created_at.isoformat(), "data": d.payload})
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        wh.SIGNATURE_HEADER: wh.sign(decrypt(e.secret_enc), ts, body),
        wh.EVENT_ID_HEADER: d.event_id,
        wh.EVENT_TYPE_HEADER: d.event_type,
        wh.TIMESTAMP_HEADER: str(ts),
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
            r = await c.post(e.url, content=body, headers=headers)
        d.last_status_code, d.last_response_ms = r.status_code, int((time.monotonic() - started) * 1000)
        if 200 <= r.status_code < 300:
            d.status, d.delivered_at, d.last_error = "delivered", utcnow(), None
            e.consecutive_failures = 0
        else:
            raise RuntimeError(f"HTTP {r.status_code}")
    except Exception as exc:
        log.warning("webhook delivery failed delivery=%s error=%s", d.id, type(exc).__name__)
        d.last_error = str(exc)[:500]
        delay = wh.next_delay(d.attempts)
        e.consecutive_failures += 1
        if delay is None:
            d.status = "failed"
        else:
            d.status, d.next_attempt_at = "pending", utcnow() + __import__("datetime").timedelta(seconds=delay)
        if e.consecutive_failures >= 10:
            e.status = "auto_disabled"
    await session.commit()
    return d.status
