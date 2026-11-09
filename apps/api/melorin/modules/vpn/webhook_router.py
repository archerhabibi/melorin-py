"""Public endpoint the PasarGuard panel calls (PG-03): ``POST /api/v1/webhooks/pasarguard/{panel_id}``.

The route only authenticates, parses, stores and answers (fast 200); every real effect happens in the worker
(:mod:`melorin.modules.vpn.panel_events`). Hardening, in the order the checks run:

1. per-IP rate limit, and a much tighter limit on *failed* secrets (brute force);
2. hard body cap (read while streaming, so a huge body is never buffered);
3. a panel that is unknown, disabled or never connected answers exactly like a wrong secret (no panel enumeration);
4. constant-time secret comparison; the secret and the body are never logged.

The panel retries on any non-2xx, so a transient problem (database down) is a 5xx on purpose and an unusable item inside a good
delivery is skipped without failing the whole batch.
"""

import hmac
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy import select

from melorin.modules.vpn.adapters import providers
from melorin.core.db import session_factory
from melorin.core.errors import AppError
from melorin.core.metrics import inc
from melorin.core.ratelimit import client_ip, hit
from melorin.kernel.models.vpn import Panel
from melorin.modules.vpn import panel_events
from melorin.modules.vpn.adapters.pasarguard import events as wire

router = APIRouter(tags=["webhooks"])
log = logging.getLogger("melorin.vpn.webhook")

PER_IP = (600, 60)  # a busy panel batches; this only stops floods
BAD_SECRET = (10, 300)  # wrong secret from one address: 10 per 5 minutes, then 429
IMMEDIATE = 50  # events processed right after the response (latency); the worker sweeps the rest


def _unauthorized() -> AppError:
    return AppError("UNAUTHORIZED", "Unauthorized.", 401)


async def _read_limited(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > wire.MAX_BODY_BYTES:
        raise AppError("PAYLOAD_TOO_LARGE", "Body too large.", 413)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > wire.MAX_BODY_BYTES:
            raise AppError("PAYLOAD_TOO_LARGE", "Body too large.", 413)
        chunks.append(chunk)
    return b"".join(chunks)


async def _process_now(panel_id: uuid.UUID) -> None:
    try:
        await panel_events.run_pending(limit=IMMEDIATE, panel_id=panel_id)
    except Exception:  # the worker sweep is the safety net; never surface this to the panel
        log.warning("immediate panel event processing failed panel=%s", panel_id, exc_info=True)


@router.post("/webhooks/pasarguard/{panel_id}", operation_id="pasarguard_webhook", include_in_schema=False)
async def pasarguard_webhook(panel_id: uuid.UUID, request: Request, background: BackgroundTasks):
    ip = client_ip(request)
    if not await hit(f"pgwh:{ip}", *PER_IP):
        raise AppError("RATE_LIMITED", "Too many requests.", 429)
    body = await _read_limited(request)

    async with session_factory()() as session:
        panel = await session.scalar(select(Panel).where(Panel.id == panel_id))
        secret = (
            panel_events.secret_for(panel)
            if panel is not None and panel.is_enabled and providers.supports(panel.kind, "webhook_events")
            else None
        )
        ok = wire.verify_secret(request.headers, secret) if secret else bool(hmac.compare_digest(b"x", b"y"))  # uniform work either way
        if not ok:
            inc("melorin_panel_webhook_rejected_total", reason="auth")
            if not await hit(f"pgwh-bad:{ip}", *BAD_SECRET):
                raise AppError("RATE_LIMITED", "Too many requests.", 429)
            raise _unauthorized()
        try:
            parsed = wire.parse_body(body)
        except ValueError as exc:
            inc("melorin_panel_webhook_rejected_total", reason="body")
            raise AppError("BAD_REQUEST", str(exc), 400) from exc
        result = await panel_events.ingest(session, panel, parsed)

    if result.accepted:
        background.add_task(_process_now, panel_id)
    return {
        "ok": True,
        "accepted": result.accepted,
        "duplicates": result.duplicates,
        "ignored": result.ignored,
        "rejected": result.rejected,
    }
