"""T01: channel binding. A session is opened THROUGH a verified channel and is bound to ONE store (docs/16-Channel-Binding-Design.md).

Everything is decided in Core: the Host of the request (site), the runner's secret + the store it names (bot), or the admin
panel's password+TOTP login (admin). A token of store A is refused on ``/stores/B/...`` before any query runs, a refresh
cannot move a session to another store, and the last tests are guards that fail when someone adds a session route that is not
bound again."""

import datetime as dt
import types
import uuid

import jwt
import pytest
from fastapi import Response
from fastapi.routing import APIRoute
from sqlalchemy import select

from _chan import admin_auth, auth_for, fake_request
from _db import make_store, make_user, open_session
from melorin.core import channel as ch
from melorin.core import deps
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.core.security import create_access_token, decode_access_token
from melorin.modules.identity import service
from melorin.modules.identity.models import RefreshToken

PROD = types.SimpleNamespace(
    is_dev=False,
    trusted_proxy_ips=["172.28.0.0/16"],
    store_web_url="https://main.example.com",
    public_api_url="https://main.example.com",
    bot_service_secret="s" * 40,
    main_bot_secret="m" * 40,
    reseller_bot_secret="r" * 40,
)


@pytest.fixture
def prod(monkeypatch):
    """Production-like channel rules (unknown hosts refused, per-runner secrets configured)."""
    monkeypatch.setattr(ch, "get_settings", lambda: PROD)
    return PROD


async def _world(s):
    owner_a, owner_b, alice, admin = [await make_user(s) for _ in range(3)] + [await make_user(s, super_admin=True)]
    main = await make_store(s, kind="main")
    main.domain = "main.example.com"
    a = await make_store(s, kind="reseller", owner=owner_a)
    a.domain = "a.example.ir"
    b = await make_store(s, kind="reseller", owner=owner_b)
    b.domain = "b.example.ir"
    await s.commit()
    return types.SimpleNamespace(**locals())


async def _codes(coro):
    with pytest.raises(AppError) as e:
        await coro
    return e.value.code


# ------------------------------------------------------------------ token claims
def test_access_token_carries_the_binding_and_parses_strictly():
    uid, sid = uuid.uuid4(), uuid.uuid4()
    claims = ch.SessionClaims.from_payload(decode_access_token(create_access_token(uid, False, store_id=sid, channel="bot")[0]))
    assert (claims.user_id, claims.channel, claims.store_id, claims.is_admin) == (uid, "bot", sid, False)
    admin = ch.SessionClaims.from_payload(decode_access_token(create_access_token(uid, True, channel="admin")[0]))
    assert admin.is_admin and admin.store_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {"sub": str(uuid.uuid4())},  # a token from before binding existed
        {"sub": str(uuid.uuid4()), "chn": "site"},  # customer session without a store
        {"sub": str(uuid.uuid4()), "chn": "admin", "sid": str(uuid.uuid4())},  # admin sessions are never store-bound
        {"sub": str(uuid.uuid4()), "chn": "mystery", "sid": str(uuid.uuid4())},
        {"sub": str(uuid.uuid4()), "chn": "site", "sid": "not-a-uuid"},
        {"sub": "not-a-uuid", "chn": "site", "sid": str(uuid.uuid4())},
    ],
)
def test_unbound_or_malformed_claims_are_refused(payload):
    with pytest.raises(AppError) as e:
        ch.SessionClaims.from_payload(payload)
    assert e.value.code == "SESSION_UNBOUND" and e.value.status == 401


async def test_a_legacy_token_without_channel_is_refused_by_the_auth_dependency():
    async with open_session() as s:
        u = await make_user(s)
        await s.commit()
        legacy = jwt.encode({"sub": str(u.id), "adm": False, "exp": 4102444800, "typ": "access"}, "test-only-jwt-signing-key-0123456789-abcdefghij", algorithm="HS256")
        creds = types.SimpleNamespace(credentials=legacy)
        assert await _codes(deps.auth_session(s, creds)) == "SESSION_UNBOUND"


async def test_demoted_admin_loses_the_admin_session_immediately():
    async with open_session() as s:
        u = await make_user(s)  # not an admin any more
        await s.commit()
        token = create_access_token(u.id, True, channel="admin")[0]
        assert await _codes(deps.auth_session(s, types.SimpleNamespace(credentials=token))) == "UNAUTHORIZED"


# ------------------------------------------------------------------ site channel (Host)
async def test_site_channel_is_decided_by_the_host_not_by_the_client(prod):
    async with open_session() as s:
        w = await _world(s)
        assert (await ch.site_channel(s, fake_request("a.example.ir"))).store_id == w.a.id
        assert (await ch.site_channel(s, fake_request("B.Example.IR:443"))).store_id == w.b.id
        assert (await ch.site_channel(s, fake_request("main.example.com"))).store_id == w.main.id
        # a client "hint" can only agree with the host
        assert (await ch.site_channel(s, fake_request("a.example.ir"), hint=w.a.id)).store_id == w.a.id
        assert await _codes(ch.site_channel(s, fake_request("a.example.ir"), hint=w.b.id)) == "CHANNEL_MISMATCH"
        assert await _codes(ch.site_channel(s, fake_request("main.example.com"), hint=w.a.id)) == "CHANNEL_MISMATCH"


async def test_unknown_host_is_refused_in_production_and_falls_back_to_main_only_in_development(prod, monkeypatch):
    async with open_session() as s:
        w = await _world(s)
        assert await _codes(ch.site_channel(s, fake_request("evil.example.org"))) == "CHANNEL_UNKNOWN"
        assert await _codes(ch.site_channel(s, fake_request(""))) == "CHANNEL_UNKNOWN"
        monkeypatch.setattr(ch, "get_settings", lambda: types.SimpleNamespace(**{**vars(PROD), "is_dev": True}))
        assert (await ch.site_channel(s, fake_request("localhost"))).store_id == w.main.id
        assert (await ch.site_channel(s, fake_request("localhost"), hint=w.a.id)).store_id == w.a.id  # dev front end on :3000


async def test_forwarded_host_counts_only_from_a_trusted_proxy(prod):
    async with open_session() as s:
        w = await _world(s)
        via_proxy = fake_request("api.internal", peer="172.28.0.5", x_forwarded_host="a.example.ir")
        assert (await ch.site_channel(s, via_proxy)).store_id == w.a.id
        spoofed = fake_request("main.example.com", peer="203.0.113.9", x_forwarded_host="a.example.ir")  # direct client lies
        assert (await ch.site_channel(s, spoofed)).store_id == w.main.id


def test_host_normalisation_rejects_garbage():
    assert ch.normalize_host("Shop.Example.IR.:8443") == "shop.example.ir"
    assert ch.normalize_host("[::1]:8000") == "::1"
    for bad in (None, "", "a b", "a/b", "user@host", "x" * 300):
        assert ch.normalize_host(bad) is None


# ------------------------------------------------------------------ bot channel (runner secret + store)
def test_runner_secrets_identify_the_runner_in_constant_time(prod):
    assert ch.identify_bot("m" * 40).kind == "main" and ch.identify_bot("r" * 40).kind == "reseller"
    assert ch.identify_bot("s" * 40).kind == "any"
    assert ch.identify_bot("") is None and ch.identify_bot("wrong") is None
    assert ch.BotService("main").may_serve("main") and not ch.BotService("main").may_serve("reseller")
    assert ch.BotService("any").may_serve("main") and ch.BotService("any").may_serve("reseller")


async def test_a_runner_can_only_open_sessions_in_stores_of_its_kind(prod):
    async with open_session() as s:
        w = await _world(s)
        main_runner, reseller_runner, shared = ch.BotService("main"), ch.BotService("reseller"), ch.BotService("any")
        assert (await ch.bot_channel(s, main_runner)).store_id == w.main.id  # no store id = the main bot
        assert (await ch.bot_channel(s, reseller_runner, w.a.id)).store_id == w.a.id
        assert (await ch.bot_channel(s, shared, w.b.id)).kind == "bot"
        assert await _codes(ch.bot_channel(s, main_runner, w.a.id)) == "CHANNEL_FORBIDDEN"  # main runner cannot enter a reseller
        assert await _codes(ch.bot_channel(s, reseller_runner, w.main.id)) == "CHANNEL_FORBIDDEN"  # ...nor the reverse
        assert await _codes(ch.bot_channel(s, shared, uuid.uuid4())) == "CHANNEL_UNKNOWN"


async def test_suspended_store_or_disabled_bot_opens_no_session(prod):
    async with open_session() as s:
        w = await _world(s)
        w.a.status = "suspended"
        w.b.bot_enabled = False
        await s.commit()
        assert await _codes(ch.bot_channel(s, ch.BotService("any"), w.a.id)) == "STORE_SUSPENDED"
        assert await _codes(ch.bot_channel(s, ch.BotService("any"), w.b.id)) == "CHANNEL_DISABLED"


# ------------------------------------------------------------------ enforcement on the customer plane
async def test_a_session_of_store_a_is_refused_on_store_b_before_any_query():
    async with open_session() as s:
        w = await _world(s)
        in_a = auth_for(w.alice, w.a)
        ctx = await deps.store_context(s, in_a, w.a.id)
        assert ctx.store.id == w.a.id and ctx.is_admin is False
        assert await _codes(deps.store_context(s, in_a, w.b.id)) == "CHANNEL_MISMATCH"
        assert await _codes(deps.store_context(s, in_a, w.main.id)) == "CHANNEL_MISMATCH"
        # an id that does not exist answers exactly like a real foreign store: no probing
        assert await _codes(deps.store_context(s, in_a, uuid.uuid4())) == "CHANNEL_MISMATCH"
        # and no membership was created in the foreign store by the failed attempts
        from melorin.modules.stores.models import StoreMembership

        rows = (await s.scalars(select(StoreMembership.store_id).where(StoreMembership.user_id == w.alice.id))).all()
        assert set(rows) == {w.a.id}


async def test_bot_and_site_sessions_of_the_same_store_are_equivalent_for_the_store_plane():
    async with open_session() as s:
        w = await _world(s)
        for kind in ("site", "bot"):
            assert (await deps.store_context(s, auth_for(w.alice, w.a, kind), w.a.id)).store.id == w.a.id


async def test_admin_panel_session_reaches_every_store_but_a_customer_session_of_an_admin_does_not():
    async with open_session() as s:
        w = await _world(s)
        ctx = await deps.store_context(s, admin_auth(w.admin), w.b.id)
        assert ctx.is_admin is True
        as_customer = auth_for(w.admin, w.a, "bot")  # the same account, but through a bot: a customer session
        assert as_customer.is_admin_session is False
        assert await _codes(deps.store_context(s, as_customer, w.b.id)) == "CHANNEL_MISMATCH"
        assert (await deps.store_context(s, as_customer, w.a.id)).is_admin is False
        assert await _codes(deps.require_admin_session(as_customer, w.admin)) == "FORBIDDEN"


async def test_owner_plane_store_own_channels_or_main_hub_for_the_real_owner_only():
    async with open_session() as s:
        w = await _world(s)
        owner_site = auth_for(w.owner_a, w.a)
        assert (await deps.owner_store_context(s, owner_site, w.a.id)).store.id == w.a.id
        assert await _codes(deps.owner_store_context(s, owner_site, w.b.id)) == "CHANNEL_MISMATCH"
        hub = auth_for(w.owner_a, w.main)  # the reseller panel on the main site
        assert (await deps.owner_store_context(s, hub, w.a.id)).store.id == w.a.id
        assert await _codes(deps.owner_store_context(s, hub, w.b.id)) == "CHANNEL_MISMATCH"  # not his store: not reachable, not joinable
        # a plain customer of the main store cannot use the main hub to reach anybody's panel
        with pytest.raises(AppError) as e:
            await deps.owner_store_context(s, auth_for(w.alice, w.main), w.a.id)
        assert e.value.code == "CHANNEL_MISMATCH"


# ------------------------------------------------------------------ issuing and rotating sessions
async def test_issue_tokens_binds_the_session_and_never_crosses_admin_and_customer():
    async with open_session() as s:
        w = await _world(s)
        site = ch.Channel("site", w.a.id, "a.example.ir", "reseller", "active", w.owner_a.id)
        pair = await service.issue_tokens(s, w.alice, site)
        claims = ch.SessionClaims.from_payload(decode_access_token(pair.access_token))
        assert (claims.channel, claims.store_id, pair.is_admin) == ("site", w.a.id, False)
        row = await s.scalar(select(RefreshToken).where(RefreshToken.user_id == w.alice.id))
        assert (row.channel, row.store_id) == ("site", w.a.id)
        assert await _codes(service.issue_tokens(s, w.admin, site)) == "ADMIN_USE_PANEL"  # admins never get a store session
        assert await _codes(service.issue_tokens(s, w.alice, ch.ADMIN_CHANNEL)) == "ADMIN_USE_PANEL"  # nobody else gets an admin one
        admin_pair = await service.issue_tokens(s, w.admin, ch.ADMIN_CHANNEL)
        assert admin_pair.is_admin and ch.SessionClaims.from_payload(decode_access_token(admin_pair.access_token)).store_id is None
        w.a.status = "suspended"
        assert await _codes(service.issue_tokens(s, w.alice, ch.Channel("site", w.a.id, None, "reseller", "suspended", w.owner_a.id))) == "STORE_SUSPENDED"
        owner = await service.issue_tokens(s, w.owner_a, ch.Channel("site", w.a.id, None, "reseller", "suspended", w.owner_a.id))
        assert owner.store_id == w.a.id  # the owner can still reach his own (suspended) panel


async def test_refresh_rotation_keeps_the_same_store_and_refuses_unbound_or_moved_families(prod):
    async with open_session() as s:
        w = await _world(s)
        site_a = await ch.site_channel(s, fake_request("a.example.ir"))
        first = await service.issue_tokens(s, w.alice, site_a)
        await s.commit()
        again = await service.rotate_refresh(s, first.refresh_token, fake_request("a.example.ir"))
        assert (again.channel, again.store_id) == ("site", w.a.id)
        # the very same refresh token, replayed on another store's domain, is refused (and the family is not revived)
        third = await service.issue_tokens(s, w.alice, site_a)
        await s.commit()
        assert await _codes(service.rotate_refresh(s, third.refresh_token, fake_request("b.example.ir"))) == "CHANNEL_MISMATCH"
        # a legacy family (no binding) must sign in again
        legacy = RefreshToken(user_id=w.alice.id, token_hash=service.token_hash("legacy"), family_id=uuid.uuid4(), expires_at=utcnow() + dt.timedelta(days=7))
        s.add(legacy)
        await s.commit()
        assert await _codes(service.rotate_refresh(s, "legacy")) == "INVALID_REFRESH"
        # an admin family rotates as an admin session
        admin_pair = await service.issue_tokens(s, w.admin, ch.ADMIN_CHANNEL)
        await s.commit()
        rotated = await service.rotate_refresh(s, admin_pair.refresh_token, fake_request("anything.example"))
        assert rotated.is_admin and rotated.store_id is None


async def test_handoff_and_login_attempts_are_store_bound(prod):
    async with open_session() as s:
        w = await _world(s)
        token = await service.create_web_handoff(s, w.alice, w.a.id)
        assert await _codes(service.redeem_web_handoff(s, token, await ch.site_channel(s, fake_request("b.example.ir")))) == "HANDOFF_INVALID"
        token = await service.create_web_handoff(s, w.alice, w.a.id)
        user = await service.redeem_web_handoff(s, token, await ch.site_channel(s, fake_request("a.example.ir")))
        assert user.id == w.alice.id


# ------------------------------------------------------------------ guards (fail when a new route is not bound)
def _api_routes():
    from melorin.app import app

    def walk(routes):
        for r in routes:
            if isinstance(r, APIRoute):
                yield r
            elif hasattr(r, "original_router"):  # include_router() in current FastAPI wraps routers
                yield from walk(r.original_router.routes)

    return list(walk(app.routes))


def _dependency_names(route):
    def flat(d):
        for x in d.dependencies:
            yield getattr(x.call, "__name__", str(x.call))
            yield from flat(x)

    return set(flat(route.dependant))


SESSION_DEPS = {"store_context", "owner_store_context", "require_admin_session", "current_auth", "auth_session", "current_user", "optional_user", "main_session_user"}
# Every route that needs no session. A NEW unauthenticated route must be added here on purpose (and reviewed).
PUBLIC_ROUTES = {
    # login / session lifecycle (they open sessions; each derives its channel itself)
    "/auth/email/request-code", "/auth/email/verify-code", "/auth/password/login", "/auth/google/config", "/auth/google/nonce",
    "/auth/google", "/auth/telegram/webapp", "/auth/web-handoff/redeem", "/auth/refresh", "/auth/logout",
    "/auth/telegram/web/sessions", "/auth/telegram/web/sessions/{session_id}/poll", "/auth/telegram/web/sessions/{session_id}/cancel",
    "/auth/telegram/config", "/auth/telegram/oidc/start", "/auth/telegram/oidc/callback",
    # runner endpoints (X-Bot-Secret + the channel rules of core.channel)
    "/auth/telegram/bot", "/auth/telegram/link", "/auth/telegram/web/bot/inspect", "/auth/telegram/web/bot/decide",
    "/internal/reseller-bots", "/internal/reseller-bots/{store_id}/status",
    # public storefront data
    "/stores/main", "/stores/by-slug/{slug}", "/stores/by-domain/{domain}", "/tls/ask", "/stores/{store_id}",
    "/stores/{store_id}/catalog", "/stores/{store_id}/bundles", "/stores/{store_id}/bundles/{bundle_id}/packages",
    # gateway server-to-server callback, reseller API (X-API-Key), probes
    "/payments/callbacks/{provider}",
    "/reseller-api/v1/stores/{store_id}/catalog", "/reseller-api/v1/stores/{store_id}/customers",
    "/reseller-api/v1/stores/{store_id}/orders", "/reseller-api/v1/stores/{store_id}/customers/{customer_id}/wallet",
    "/reseller-api/v1/stores/{store_id}/reports",
    "/health/live", "/healthz", "/health/ready", "/health", "/openapi-version", "/metrics",
}


def test_the_public_surface_is_exactly_the_reviewed_list():
    open_routes = {r.path for r in _api_routes() if not (_dependency_names(r) & SESSION_DEPS)}
    assert open_routes == PUBLIC_ROUTES, f"unexpected: {sorted(open_routes - PUBLIC_ROUTES)} / gone: {sorted(PUBLIC_ROUTES - open_routes)}"


def test_every_store_scoped_route_uses_the_channel_checked_dependency():
    for r in _api_routes():
        if "{store_id}" in r.path and r.path not in PUBLIC_ROUTES:
            names = _dependency_names(r)
            assert names & {"store_context", "owner_store_context", "require_admin_session"}, f"{r.path} must resolve store_context/owner_store_context"


def test_every_admin_route_needs_an_admin_panel_session():
    admin_routes = [r for r in _api_routes() if r.path.startswith(("/admin", "/reports")) or "/admin/" in r.path]
    assert len(admin_routes) > 50
    for r in admin_routes:
        assert "require_admin_session" in _dependency_names(r), f"{r.path} is reachable without an admin-panel session"


def test_sessions_are_only_opened_through_a_channel_and_admin_is_only_built_after_totp():
    from pathlib import Path

    root = Path(__file__).parents[1] / "melorin"
    for p in root.rglob("*.py"):
        src = p.read_text()
        for line in src.splitlines():
            if "issue_tokens(" in line and "def issue_tokens" not in line:
                assert "chan" in line or "site" in line or "ADMIN_CHANNEL" in line, f"{p.name}: issue_tokens without a verified channel: {line.strip()}"
    # the admin channel is constructed in exactly the password+TOTP and Google+TOTP admin handlers
    users = [p.name for p in root.rglob("*.py") if "ADMIN_CHANNEL" in p.read_text() and p.name not in {"channel.py"}]
    assert sorted(set(users)) == ["router.py", "service.py"]
    router_src = (root / "modules/identity/router.py").read_text()
    assert router_src.count("channel.ADMIN_CHANNEL") == 2
    assert "decode_access_token" not in "".join(p.read_text() for p in (root / "modules").rglob("*.py"))  # only core.deps reads tokens
