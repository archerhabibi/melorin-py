"""T03: the reseller API key is the fourth channel (``api``) of docs/16-Channel-Binding-Design.md.

Same rule as sessions: Core derives the store from the KEY (never from the URL), the ``store_id`` in the path may only agree with
it, and that comparison happens before any store row is read. Everything is decided in ``core.channel.api_channel``; the routes
only declare the scope they need (``core.deps.api_access``).
"""

import datetime as dt
import types
import uuid

import pytest
from sqlalchemy import select

from _db import make_store, make_user, open_session
from melorin.core import channel as ch
from melorin.core import deps, metrics
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.modules.reseller import api_keys
from melorin.modules.stores.models import ApiCredential, ResellerProfile

ALL_SCOPES = sorted(api_keys.ALLOWED_SCOPES)


async def _world(s, *, api_enabled=True):
    owner_a, owner_b = await make_user(s), await make_user(s)
    main = await make_store(s, kind="main")
    a = await make_store(s, kind="reseller", owner=owner_a)
    b = await make_store(s, kind="reseller", owner=owner_b)
    for st, owner in ((a, owner_a), (b, owner_b)):
        s.add(ResellerProfile(store_id=st.id, user_id=owner.id, debt_limit=0, api_enabled=api_enabled, sales_enabled=True))
    await s.commit()
    return types.SimpleNamespace(**locals())


async def _key(s, store, owner, *, scopes=None, ips=None, active=True, expires_at=None) -> str:
    body = types.SimpleNamespace(
        name="k", scopes=scopes or ["catalog:read"], activate=active, rate_limit_per_minute=120, ip_allowlist=ips, expires_at=expires_at
    )
    _, raw = await api_keys.create(s, store, owner, body)
    return raw


async def _code(coro) -> str:
    with pytest.raises(AppError) as e:
        await coro
    return e.value.code


def _open(s, raw, store, scope="catalog:read", ip="203.0.113.9"):
    return ch.api_channel(s, raw, store_id=store.id, scope=scope, ip=ip)


# ------------------------------------------------------------------ the binding
async def test_the_key_opens_the_api_channel_of_its_own_store():
    async with open_session() as s:
        w = await _world(s)
        raw = await _key(s, w.a, w.owner_a)
        access = await _open(s, raw, w.a)
        c = access.channel
        assert (c.kind, c.store_id, c.store_kind, c.owner_user_id) == (ch.API, w.a.id, "reseller", w.owner_a.id)
        assert c.credential_id == access.credential.id and c.ref == access.credential.key_prefix
        assert access.store.id == w.a.id
        assert access.credential.last_used_at is not None


async def test_a_key_of_store_a_is_refused_on_store_b_before_any_store_lookup():
    async with open_session() as s:
        w = await _world(s)
        raw = await _key(s, w.a, w.owner_a)
        before = metrics._counters.get(("melorin_channel_rejected_total", (("reason", "api_store_mismatch"),)), 0)
        # existing foreign store and a store id that does not exist: the very same answer (nothing to probe)
        assert await _code(_open(s, raw, w.b)) == "API_STORE_ISOLATION"
        assert await _code(ch.api_channel(s, raw, store_id=uuid.uuid4(), scope="catalog:read", ip=None)) == "API_STORE_ISOLATION"
        assert metrics._counters[("melorin_channel_rejected_total", (("reason", "api_store_mismatch"),))] == before + 2


async def test_the_main_store_hub_does_not_exist_for_api_keys():
    """A key is never accepted for the main store, even if a row pointing at it were forged."""
    async with open_session() as s:
        w = await _world(s)
        s.add(ResellerProfile(store_id=w.main.id, user_id=w.owner_a.id, debt_limit=0, api_enabled=True, sales_enabled=True))
        raw = await _key(s, w.main, w.owner_a)
        assert await _code(_open(s, raw, w.main)) == "API_DISABLED"


def test_a_session_token_can_never_claim_the_api_channel():
    assert ch.API not in ch.CHANNELS
    payload = {"sub": str(uuid.uuid4()), "chn": "api", "sid": str(uuid.uuid4())}
    with pytest.raises(AppError) as e:
        ch.SessionClaims.from_payload(payload)
    assert e.value.code == "SESSION_UNBOUND"


# ------------------------------------------------------------------ the key itself
@pytest.mark.parametrize("raw", [None, "", "   ", "not-a-key", "mln_live_" + "x" * 43, "Bearer mln_live_abc"])
async def test_unknown_or_malformed_keys_are_unauthorized(raw):
    async with open_session() as s:
        w = await _world(s)
        assert await _code(_open(s, raw, w.a)) == "API_UNAUTHORIZED"


async def test_disabled_revoked_and_expired_keys_are_unauthorized():
    async with open_session() as s:
        w = await _world(s)
        disabled = await _key(s, w.a, w.owner_a, active=False)
        expired = await _key(s, w.a, w.owner_a, expires_at=utcnow() - dt.timedelta(seconds=1))
        revoked = await _key(s, w.a, w.owner_a)
        cred = await s.scalar(select(ApiCredential).where(ApiCredential.key_hash == api_keys.hash_key(revoked)))
        await api_keys.set_status(s, cred, "revoke", w.owner_a)
        for raw in (disabled, expired, revoked):
            assert await _code(_open(s, raw, w.a)) == "API_UNAUTHORIZED"


async def test_rotation_retires_the_old_key_and_the_new_one_works():
    async with open_session() as s:
        w = await _world(s)
        old = await _key(s, w.a, w.owner_a)
        cred = await s.scalar(select(ApiCredential).where(ApiCredential.key_hash == api_keys.hash_key(old)))
        _, new = await api_keys.rotate(s, cred, w.owner_a)
        assert await _code(_open(s, old, w.a)) == "API_UNAUTHORIZED"
        assert (await _open(s, new, w.a)).channel.store_id == w.a.id


async def test_scope_is_enforced():
    async with open_session() as s:
        w = await _world(s)
        raw = await _key(s, w.a, w.owner_a, scopes=["catalog:read"])
        assert (await _open(s, raw, w.a, scope="catalog:read")).channel.kind == ch.API
        assert await _code(_open(s, raw, w.a, scope="customers:wallet:write")) == "API_SCOPE_FORBIDDEN"


async def test_ip_allowlist_is_enforced_and_fails_closed():
    async with open_session() as s:
        w = await _world(s)
        pinned = await _key(s, w.a, w.owner_a, ips=["198.51.100.0/24"])
        assert (await _open(s, pinned, w.a, ip="198.51.100.7")).channel.store_id == w.a.id
        assert await _code(_open(s, pinned, w.a, ip="203.0.113.9")) == "API_IP_FORBIDDEN"
        assert await _code(_open(s, pinned, w.a, ip=None)) == "API_IP_FORBIDDEN"  # unresolvable peer
        assert await _code(_open(s, pinned, w.a, ip="?")) == "API_IP_FORBIDDEN"
        open_key = await _key(s, w.a, w.owner_a)  # no allowlist = any address
        assert (await _open(s, open_key, w.a, ip=None)).channel.kind == ch.API


async def test_ip_is_checked_before_scope_so_a_foreign_address_learns_nothing_about_the_key():
    async with open_session() as s:
        w = await _world(s)
        raw = await _key(s, w.a, w.owner_a, scopes=["catalog:read"], ips=["198.51.100.0/24"])
        assert await _code(_open(s, raw, w.a, scope="reports:read", ip="203.0.113.9")) == "API_IP_FORBIDDEN"


# ------------------------------------------------------------------ the store behind the key
async def test_api_must_be_enabled_for_the_store():
    async with open_session() as s:
        w = await _world(s, api_enabled=False)
        raw = await _key(s, w.a, w.owner_a)
        assert await _code(_open(s, raw, w.a)) == "API_DISABLED"


async def test_a_suspended_store_takes_no_api_traffic():
    async with open_session() as s:
        w = await _world(s)
        raw = await _key(s, w.a, w.owner_a)
        w.a.status = "suspended"
        await s.commit()
        assert await _code(_open(s, raw, w.a)) == "STORE_SUSPENDED"
        assert (await _open(s, await _key(s, w.b, w.owner_b), w.b)).channel.store_id == w.b.id  # other stores are unaffected


# ------------------------------------------------------------------ the dependency routes use
async def test_dependency_yields_the_owner_context_of_the_keys_store():
    async with open_session() as s:
        w = await _world(s)
        raw = await _key(s, w.a, w.owner_a, scopes=["reports:read"])
        dep = deps.api_access("reports:read")
        ctx = await dep(session=s, store_id=w.a.id, x_api_key=raw)
        assert (ctx.store.id, ctx.user.id, ctx.is_owner, ctx.is_admin) == (w.a.id, w.owner_a.id, True, False)
        assert await _code(dep(session=s, store_id=w.b.id, x_api_key=raw)) == "API_STORE_ISOLATION"
        assert await _code(dep(session=s, store_id=w.a.id, x_api_key="")) == "API_UNAUTHORIZED"  # missing header = 401, not 422


async def test_a_deactivated_owner_cannot_use_the_key():
    async with open_session() as s:
        w = await _world(s)
        raw = await _key(s, w.a, w.owner_a)
        w.owner_a.is_active = False
        await s.commit()
        assert await _code(deps.api_access("catalog:read")(session=s, store_id=w.a.id, x_api_key=raw)) == "API_DISABLED"


def test_every_reseller_api_route_declares_its_scope_through_the_core_dependency():
    from fastapi.routing import APIRoute

    from melorin.modules.reseller.router import api_router

    routes = [r for r in api_router.routes if isinstance(r, APIRoute)]
    assert len(routes) == 5
    for r in routes:
        names = {getattr(d.call, "__name__", "") for d in r.dependant.dependencies}
        assert "api_store_context" in names, f"{r.path} bypasses the api channel"
        # the key and the store never come from the handler's own parameters any more
        assert not {p.name for p in r.dependant.header_params} - {"x_api_key"}


def test_the_key_module_no_longer_authenticates_anything_itself():
    assert not hasattr(api_keys, "authenticate")  # one place decides: core.channel.api_channel


# ------------------------------------------------------------------ over real HTTP (FastAPI wiring: header, path, error body)
async def test_over_http_the_key_decides_the_store_and_errors_keep_their_public_codes():
    import httpx
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from _db import open_schema_engine
    from melorin.app import app
    from melorin.core.db import get_session

    async with open_schema_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            w = await _world(s)
            raw_a = await _key(s, w.a, w.owner_a, scopes=["catalog:read", "reports:read"])
            raw_b = await _key(s, w.b, w.owner_b, scopes=["reports:read"])

        async def _session():
            async with maker() as session:
                yield session

        app.dependency_overrides[get_session] = _session
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                base = "/api/v1/reseller-api/v1/stores"

                async def get(path, key=None):
                    r = await c.get(f"{base}/{path}", headers={"X-API-Key": key} if key else {})
                    return r.status_code, (r.json().get("error", {}).get("code") if r.status_code >= 400 else r.json())

                assert await get(f"{w.a.id}/reports", raw_a) == (200, {"store_id": str(w.a.id), "currency": w.a.currency, "orders": []})
                assert await get(f"{w.a.id}/reports") == (401, "API_UNAUTHORIZED")  # no header: 401, not 422
                assert await get(f"{w.a.id}/reports", "mln_live_nope") == (401, "API_UNAUTHORIZED")
                assert await get(f"{w.b.id}/reports", raw_a) == (403, "API_STORE_ISOLATION")  # A's key on B's URL
                assert await get(f"{uuid.uuid4()}/reports", raw_a) == (403, "API_STORE_ISOLATION")  # ... and on a store that is not there
                assert await get(f"{w.b.id}/reports", raw_b) == (200, {"store_id": str(w.b.id), "currency": w.b.currency, "orders": []})
                assert await get(f"{w.b.id}/catalog", raw_b) == (403, "API_SCOPE_FORBIDDEN")
        finally:
            app.dependency_overrides.pop(get_session, None)
