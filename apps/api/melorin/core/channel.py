"""Channel binding: Core decides, from facts it can verify, WHICH STORE a session belongs to (docs/16-Channel-Binding-Design.md).

Why (business rule, non-negotiable): a request that comes from the website or the bot of store A must only ever act on
store A. ``core.scope`` already guarantees that a customer sees only HIS rows inside the store named in the URL; what it
cannot know is whether the caller is really "in" that store. Before this module the login token was global and the store
came from the path, so a token minted on site A worked on ``/stores/B/...`` (a technical user, a leaked token, a bug in a
channel). Now:

* every session is opened **through a channel** (``site`` | ``bot`` | ``admin``) and is **bound to one store**;
* Core derives that pair itself (the client never chooses it):
    - ``site``: the effective Host of the request (``X-Forwarded-Host`` only from a trusted proxy) must be the registered
      ``Store.domain`` of a store, or one of the main store's hosts;
    - ``bot``: the runner proves itself with its secret, and Core checks the store it names (active, bot enabled, and of
      the kind that runner is allowed to serve);
    - ``admin``: only the admin panel's password+TOTP / Google+TOTP login builds it (platform-wide, never store-bound);
* the binding travels in the access token (``chn``/``sid``) and in the refresh-token family, so rotating a session can never
  move it to another store;
* every ``/stores/{store_id}/...`` dependency compares ``sid`` with the path **before touching the database**.

A session token without a valid binding does not exist any more (it is refused with ``SESSION_UNBOUND``).
"""

from __future__ import annotations

import dataclasses
import hmac
import logging
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

from melorin.core.config import get_settings
from melorin.core.errors import AppError
from melorin.core.metrics import inc
from melorin.core.proxy import is_trusted_proxy

log = logging.getLogger("melorin.channel")

SITE, BOT, ADMIN = "site", "bot", "admin"
CHANNELS = (SITE, BOT, ADMIN)


# ---------------------------------------------------------------------------------------------- errors
def unbound() -> AppError:
    return AppError("SESSION_UNBOUND", "این نشست قدیمی است؛ دوباره وارد شوید.", 401)


def mismatch() -> AppError:
    return AppError("CHANNEL_MISMATCH", "این نشست برای فروشگاه دیگری صادر شده است؛ از همان فروشگاه وارد شوید.", 403)


def unknown() -> AppError:
    return AppError("CHANNEL_UNKNOWN", "این آدرس به هیچ فروشگاهی متصل نیست.", 403)


# ---------------------------------------------------------------------------------------------- values
@dataclasses.dataclass(frozen=True)
class Channel:
    """Where a session is being opened. ``store_id`` is ``None`` only for the admin panel.

    The other fields are a snapshot of the store rows the binding rules need (so nobody re-reads the store after a commit).
    """

    kind: str
    store_id: uuid.UUID | None
    ref: str | None = None  # host / bot username: audit and logs only, never a decision input
    store_kind: str | None = None  # main | reseller
    store_status: str | None = None
    owner_user_id: uuid.UUID | None = None

    @property
    def is_admin(self) -> bool:
        return self.kind == ADMIN

    def ensure_open_for(self, user: Any) -> None:
        """A suspended store takes no new sessions, except for its own owner (who must still reach the panel)."""
        if self.store_status not in (None, "active") and self.owner_user_id != user.id:
            raise AppError("STORE_SUSPENDED", "این فروشگاه موقتاً غیرفعال است.", 403)


# The only admin channel. Built by the admin password+TOTP / Google+TOTP handlers, nowhere else.
ADMIN_CHANNEL = Channel(ADMIN, None, "admin-panel")


@dataclasses.dataclass(frozen=True)
class SessionClaims:
    """What a verified access token says about the session (never about the user's rights: those come from the database)."""

    user_id: uuid.UUID
    channel: str
    store_id: uuid.UUID | None

    @property
    def is_admin(self) -> bool:
        return self.channel == ADMIN

    @classmethod
    def from_payload(cls, payload: dict) -> SessionClaims:
        """Strict parse. A token that does not carry a valid binding (e.g. issued before binding existed) is refused."""
        try:
            user_id = uuid.UUID(str(payload["sub"]))
            channel = payload["chn"]
            sid = payload.get("sid")
            store_id = uuid.UUID(str(sid)) if sid else None
        except (KeyError, ValueError, TypeError, AttributeError):
            raise unbound() from None
        if channel not in CHANNELS or (channel == ADMIN) != (store_id is None):
            raise unbound()
        return cls(user_id=user_id, channel=channel, store_id=store_id)


@dataclasses.dataclass(frozen=True)
class BotService:
    """Which runner is calling (decided by WHICH secret it presented, see ``core.deps.require_bot_service``).

    ``any`` is the shared ``MELORIN_BOT_SERVICE_SECRET`` (legacy, serves every store); ``main`` / ``reseller`` are the
    optional per-runner secrets, which can only open sessions in stores of that kind.
    """

    kind: str  # any | main | reseller

    def may_serve(self, store_kind: str) -> bool:
        return self.kind in ("any", store_kind)


def identify_bot(presented: str) -> BotService | None:
    """Constant-time match of a presented runner secret against every configured one (no early exit on the first hit)."""
    s = get_settings()
    given = (presented or "").encode()
    # Strict mode: once BOTH per-runner secrets exist, the shared secret is retired (a leaked copy of it, e.g. in an old .env
    # backup, opens nothing). With only one (or none) configured it keeps working, so existing installs upgrade gradually.
    candidates = [("reseller", s.reseller_bot_secret), ("main", s.main_bot_secret)]
    if not (s.main_bot_secret and s.reseller_bot_secret):
        candidates.append(("any", s.bot_service_secret))
    found: BotService | None = None
    for kind, secret in candidates:
        if secret and hmac.compare_digest(given, secret.encode()) and found is None:
            found = BotService(kind)
    return found


# ---------------------------------------------------------------------------------------------- host
def normalize_host(raw: str | None) -> str | None:
    """``Example.COM:443`` -> ``example.com``; ``None`` for anything that cannot be a hostname."""
    if not raw:
        return None
    host = raw.split(",")[0].strip().lower()
    if host.startswith("["):  # [::1]:8000
        host = host[1:].split("]")[0]
    else:
        host = host.split(":")[0]
    host = host.rstrip(".")
    if not host or len(host) > 253 or any(ch in host for ch in " /\\@?#"):
        return None
    return host


def request_host(request: Any) -> str | None:
    """The hostname the visitor used. ``X-Forwarded-Host`` counts only when the direct peer is a trusted proxy (same rule
    as the client IP); anyone else can only present the plain ``Host`` header."""
    s = get_settings()
    peer = request.client.host if getattr(request, "client", None) else None
    if is_trusted_proxy(peer, s.trusted_proxy_ips):
        forwarded = request.headers.get("x-forwarded-host")
        if forwarded:
            return normalize_host(forwarded)
    return normalize_host(request.headers.get("host"))


def _host_of_url(url: str | None) -> str | None:
    try:
        return normalize_host(urlparse(url or "").hostname)
    except ValueError:
        return None


def main_hosts(main: Any) -> set[str]:
    """Hostnames that belong to the main store: its own ``domain`` plus the configured public web/API URLs."""
    s = get_settings()
    return {h for h in (normalize_host(main.domain), _host_of_url(s.store_web_url), _host_of_url(s.public_api_url)) if h}


def _snapshot(kind: str, store: Any, ref: str | None) -> Channel:
    return Channel(kind, store.id, ref, store.kind, store.status, store.owner_user_id)


async def _main(session) -> Any:
    from melorin.modules.stores.models import Store

    main = await session.scalar(select(Store).where(Store.kind == "main"))
    if main is None:
        raise AppError("MAIN_STORE_MISSING", "فروشگاه اصلی پیکربندی نشده است.", 500)
    return main


# ---------------------------------------------------------------------------------------------- resolvers
async def site_channel(session, request: Any, *, hint: uuid.UUID | None = None) -> Channel:
    """The store whose website this request came through.

    ``hint`` is a store id the client mentioned (an old body field, a stored login attempt, a handoff). It can only AGREE with
    what the Host says; it never selects the store, except in development where a localhost front end has no store domain.
    """
    from melorin.modules.stores.models import Store

    host = request_host(request)
    store = await session.scalar(select(Store).where(Store.domain == host)) if host else None
    if store is None:
        main = await _main(session)
        if host and host in main_hosts(main):
            store = main
        elif get_settings().is_dev:
            store = (await session.get(Store, hint) if hint else None) or main
        else:
            inc("melorin_channel_rejected_total", reason="unknown_host")
            log.warning("site channel: unknown host %r", host)
            raise unknown()
    if hint is not None and hint != store.id:
        inc("melorin_channel_rejected_total", reason="hint_mismatch")
        raise mismatch()
    return _snapshot(SITE, store, host)


async def bot_channel(session, bot: BotService, store_id: uuid.UUID | None = None) -> Channel:
    """The store a trusted runner serves. ``store_id`` omitted means the main store (the main bot)."""
    from melorin.modules.stores.models import Store

    store = await session.get(Store, store_id) if store_id else await _main(session)
    if store is None:
        raise unknown()
    if not bot.may_serve(store.kind):
        inc("melorin_channel_rejected_total", reason="runner_kind")
        raise AppError("CHANNEL_FORBIDDEN", "این ربات اجازه‌ی کار با این فروشگاه را ندارد.", 403)
    if store.status != "active":
        raise AppError("STORE_SUSPENDED", "این فروشگاه موقتاً غیرفعال است.", 403)
    if store.kind == "reseller" and not store.bot_enabled:
        raise AppError("CHANNEL_DISABLED", "ربات این فروشگاه غیرفعال است.", 403)
    return _snapshot(BOT, store, store.bot_username)


def of_refresh_row(row: Any) -> Channel:
    """The binding a refresh-token family was created with (rotation re-issues exactly this)."""
    return Channel(row.channel, row.store_id)


# ---------------------------------------------------------------------------------------------- enforcement
def ensure_store(claims: SessionClaims, store_id: uuid.UUID) -> None:
    """Customer plane: the session may act only in the store it was opened for (admin sessions are platform-wide).

    Runs before any database read, so a foreign store id gets the same answer whether it exists or not.
    """
    if claims.is_admin or claims.store_id == store_id:
        return
    inc("melorin_channel_rejected_total", reason="store_mismatch")
    log.warning("channel mismatch: session bound to %s used on %s", claims.store_id, store_id)
    raise mismatch()


async def ensure_owner_store(session, claims: SessionClaims, user_id: uuid.UUID, store_id: uuid.UUID) -> None:
    """Owner plane (reseller panel): the store's own channels, OR the main store acting as the account hub - but then only
    for a store the user really owns, so a main-store session can neither reach nor even join somebody else's store."""
    from melorin.modules.stores.models import Store

    if claims.is_admin or claims.store_id == store_id:
        return
    main = await _main(session)
    owns = await session.scalar(select(Store.id).where(Store.id == store_id, Store.owner_user_id == user_id))
    if claims.store_id == main.id and owns is not None:
        return
    inc("melorin_channel_rejected_total", reason="owner_store_mismatch")
    raise mismatch()
