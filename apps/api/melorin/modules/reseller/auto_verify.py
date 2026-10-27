"""Automatic identity verification of reseller applications (docs/21).

What used to need an admin's hand is now checked by Core on a schedule:

* **Bot**: when Telegram was unreachable at filing time, the token is re-checked with back-off until Telegram answers.
* **Domain control**: the applicant proves the domain is theirs with one of two proofs, whichever is easier for them
  - a DNS TXT record ``_melorin-verify.<domain>`` = ``melorin-verify=<code>``, or
  - a file ``https://<domain>/.well-known/melorin-verify.txt`` whose content is ``melorin-verify=<code>``.

The code is derived (HMAC of the application id and domain with the server secret): nothing extra is stored, it changes
when the domain changes, and it cannot be guessed for somebody else's application. The checks only read; they never
send the code anywhere. Hosts that resolve to private / loopback addresses are refused (no SSRF through a "domain").

Everything here is pure or takes an injectable transport, so tests never touch the network.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import ipaddress
import logging
import socket

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.config import get_settings
from melorin.core.crypto import decrypt
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.stores import ResellerApplication
from melorin.modules.reseller import identity

log = logging.getLogger("melorin.reseller.verify")

TXT_PREFIX = "_melorin-verify"
HTTP_PATH = "/.well-known/melorin-verify.txt"
DOH_URL = "https://cloudflare-dns.com/dns-query"
# After attempt n the next one is due BACKOFF[min(n-1, last)] later: quick at first, then every few hours.
BACKOFF = (dt.timedelta(minutes=2), dt.timedelta(minutes=5), dt.timedelta(minutes=15), dt.timedelta(hours=1), dt.timedelta(hours=6))
BATCH = 50
MAX_PROOF_BYTES = 512  # the proof file is one short line; anything bigger is not it


def _aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=value.tzinfo or dt.UTC)


# ---------------------------------------------------------------- pure -------------------------------------------------
def challenge_code(app_id, domain: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"reseller-domain:{app_id}:{domain}".encode(), hashlib.sha256).hexdigest()[:32]


def challenge_value(app_id, domain: str) -> str:
    return f"melorin-verify={challenge_code(app_id, domain)}"


def instructions(a: ResellerApplication) -> dict | None:
    """What the applicant must publish. None until a domain is known."""
    if not a.domain:
        return None
    value = challenge_value(a.id, a.domain)
    return {
        "domain": a.domain,
        "dns": {"type": "TXT", "name": f"{TXT_PREFIX}.{a.domain}", "value": value},
        "http": {"url": f"https://{a.domain}{HTTP_PATH}", "content": value},
        "verified": a.domain_verified_at is not None,
        "method": a.domain_method,
        "error": a.verify_error,
        "next_check_at": a.verify_next_at,
    }


def _txt_matches(answers: list[dict], value: str) -> bool:
    for ans in answers or []:
        if ans.get("type") == 16 and str(ans.get("data", "")).replace('"', "").replace(" ", "") == value:
            return True
    return False


def is_public_ip(raw: str) -> bool:
    try:
        return ipaddress.ip_address(raw).is_global
    except ValueError:
        return False


async def host_is_public(domain: str) -> bool:
    """Every address the name resolves to must be public (a name pointing at 10.x / 127.x is refused)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addrs = {i[4][0] for i in infos}
    return bool(addrs) and all(is_public_ip(a) for a in addrs)


# ---------------------------------------------------------------- network ----------------------------------------------
async def check_dns(domain: str, value: str, *, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    try:
        async with httpx.AsyncClient(timeout=8, transport=transport) as client:
            r = await client.get(
                DOH_URL, params={"name": f"{TXT_PREFIX}.{domain}", "type": "TXT"}, headers={"accept": "application/dns-json"}
            )
        return r.status_code == 200 and _txt_matches((r.json() or {}).get("Answer"), value)
    except (httpx.HTTPError, ValueError):
        return False


async def check_http(domain: str, value: str, *, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    if transport is None and not await host_is_public(domain):
        return False
    try:
        async with httpx.AsyncClient(timeout=8, transport=transport, follow_redirects=False) as client:
            # Streamed and capped: a hostile domain must not be able to make the worker buffer an endless body.
            async with client.stream("GET", f"https://{domain}{HTTP_PATH}") as r:
                if r.status_code != 200:
                    return False
                body = b""
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_PROOF_BYTES:
                        return False
        return body.decode("utf-8", errors="replace").strip() == value
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------- state machine ----------------------------------------
def _complete(a: ResellerApplication) -> bool:
    return (a.bot_verified or not a.bot_token_enc) and (a.domain_verified_at is not None or not a.domain)


def _schedule(a: ResellerApplication, now: dt.datetime) -> None:
    window = dt.timedelta(days=max(1, int(get_settings().reseller_verify_window_days)))
    if _complete(a):
        a.verify_next_at, a.verify_error = None, None
    elif _aware(a.created_at) + window < now:
        a.verify_next_at = None  # gave up automatically; "verify now" starts a fresh window
        a.verify_error = a.verify_error or "window_expired"
    else:
        a.verify_next_at = now + BACKOFF[min(max(a.verify_attempts, 1) - 1, len(BACKOFF) - 1)]


async def verify(
    session: AsyncSession,
    a: ResellerApplication,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    dns_transport: httpx.AsyncBaseTransport | None = None,
    actor_id=None,
) -> ResellerApplication:
    """Run every outstanding check once and reschedule. Idempotent; never raises for a failed proof (it is recorded)."""
    now = utcnow()
    was_complete = _complete(a)
    a.verify_attempts = (a.verify_attempts or 0) + 1
    errors: list[str] = []

    if a.bot_token_enc and not a.bot_verified:
        try:
            username = await identity.verify_bot(decrypt(a.bot_token_enc), transport=transport)
        except AppError as exc:
            errors.append(exc.code if hasattr(exc, "code") else "bot_rejected")
        else:
            if username is None:
                errors.append("telegram_unreachable")
            else:
                a.bot_username, a.bot_verified = username, True
                audit.record(
                    session,
                    "reseller.application_bot_auto_verified",
                    actor_id=actor_id,
                    entity_type="reseller_application",
                    entity_id=a.id,
                    data={"bot_username": username},
                )

    if a.domain and a.domain_verified_at is None:
        value = challenge_value(a.id, a.domain)
        method = "dns" if await check_dns(a.domain, value, transport=dns_transport) else None
        if method is None and await check_http(a.domain, value, transport=transport):
            method = "http"
        if method:
            a.domain_verified_at, a.domain_method = now, method
            audit.record(
                session,
                "reseller.application_domain_verified",
                actor_id=actor_id,
                entity_type="reseller_application",
                entity_id=a.id,
                data={"domain": a.domain, "method": method},
            )
        else:
            errors.append("domain_proof_not_found")

    a.verify_error = ",".join(errors)[:200] or None
    _schedule(a, now)
    if _complete(a) and not was_complete:
        await _announce_ready(session, a)
    return a


async def _announce_ready(session: AsyncSession, a: ResellerApplication) -> None:
    from melorin.modules.reseller import auto_approve, onboarding

    audit.record(
        session, "reseller.application_auto_verified", entity_type="reseller_application", entity_id=a.id, data={"domain": a.domain}
    )
    if await auto_approve.try_approve(session, a):  # policy says fully proven applications approve themselves
        return
    await onboarding.alert_admins(
        session,
        kind="admin_reseller_verified",
        title="✅ هویت متقاضی نمایندگی به‌طور خودکار تأیید شد",
        body=f"«{a.store_name}»: ربات و مالکیت دامنه{(' ' + a.domain) if a.domain else ''} تأیید شد؛ آمادهٔ تصمیم‌گیری شماست.",
        key=f"reseller_verified:{a.id}",
    )


def restart(a: ResellerApplication) -> None:
    """The applicant asks for an immediate re-check: a fresh retry window and due now."""
    a.verify_attempts, a.verify_error, a.verify_next_at = 0, None, utcnow()


async def sweep(session: AsyncSession, *, transport=None, dns_transport=None) -> int:
    """Verify every pending application whose check is due. Returns how many were processed."""
    if not get_settings().reseller_auto_verify:
        return 0
    rows = (
        await session.scalars(
            select(ResellerApplication)
            .where(
                ResellerApplication.status == "pending",
                ResellerApplication.verify_next_at.is_not(None),
                ResellerApplication.verify_next_at <= utcnow(),
            )
            .order_by(ResellerApplication.verify_next_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for a in rows:
        try:
            await verify(session, a, transport=transport, dns_transport=dns_transport)
        except Exception:  # one broken application must not stop the others
            log.exception("auto verify failed application=%s", a.id)
            a.verify_next_at = utcnow() + BACKOFF[-1]
    await session.commit()
    return len(rows)


def proof_required_blocks(a: ResellerApplication) -> bool:
    """True when policy demands domain proof and this application has a domain that is not proven yet."""
    return bool(get_settings().reseller_require_domain_proof and a.domain and a.domain_verified_at is None)
