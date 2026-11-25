"""Authorization matrix over the whole OpenAPI surface (audit SEC-001, AI-02).

Negative controls, run against every operation that declares the bearer scheme:

* anonymous caller                                  -> 401/403, never a 2xx and never a 5xx;
* ordinary customer token on ``/admin/**``           -> 401/403;
* customer token against another store's ``{store_id}`` -> 401/403/404.

A new route that forgets its dependency, or an admin route guarded only by "is logged in", fails here without anyone having to
remember to write a per-route test.
"""

from __future__ import annotations

import re
import uuid

from _db import make_store
from _http import PASSWORD, add_user, api_client
from melorin.app import app

_METHODS = ("get", "post", "put", "patch", "delete")
_WITH_BODY = ("POST", "PUT", "PATCH")
_PARAM = re.compile(r"\{([^}]+)\}")

# "<probe> <METHOD> <path>" -> why that answer is correct. Keep it empty unless a reviewer can defend the entry.
ALLOWED: dict[str, str] = {}


def _bearer_ops() -> list[tuple[str, str, dict]]:
    spec = app.openapi()
    return [
        (method.upper(), path, op)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in _METHODS and op.get("security")
    ]


def _fill(path: str, op: dict, store_id: str | None = None) -> str:
    """Path parameters with a value of the declared type, so authorization (not validation) is what answers."""
    declared = {p["name"]: p.get("schema", {}) for p in op.get("parameters", []) if p.get("in") == "path"}

    def pick(match: re.Match) -> str:
        name = match.group(1)
        if name == "store_id" and store_id:
            return store_id
        schema = declared.get(name, {})
        if "enum" in schema:
            return str(schema["enum"][0])
        if schema.get("type") == "integer":
            return "1"
        if schema.get("format") == "uuid":
            return str(uuid.uuid4())
        return "x"

    return _PARAM.sub(pick, path)


async def _status(client, method: str, path: str, headers: dict) -> int:
    kwargs: dict = {"headers": headers}
    if method in _WITH_BODY:
        kwargs["json"] = {}
    return (await client.request(method, path, **kwargs)).status_code


async def _customer(client, maker) -> tuple[dict, str]:
    """A logged-in ordinary customer and the id of a second, unrelated store."""
    await add_user(maker, email="customer@example.com")
    r = await client.post("/api/v1/auth/password/login", json={"email": "customer@example.com", "password": PASSWORD})
    assert r.status_code == 200, r.text
    async with maker() as s:
        other = await make_store(s, kind="reseller", slug="other-shop")
        await s.commit()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, str(other.id)


def _report(probe: str, offenders: list[str]) -> str:
    return f"{probe}: {len(offenders)} operation(s) answered outside the allowed statuses:\n  " + "\n  ".join(offenders)


async def test_anonymous_callers_are_rejected_everywhere() -> None:
    offenders = []
    async with api_client() as (c, _maker, _main):
        for method, path, op in _bearer_ops():
            status = await _status(c, method, _fill(path, op), {})
            if status not in (401, 403) and f"anon {method} {path}" not in ALLOWED:
                offenders.append(f"{method} {path} -> {status}")
    assert not offenders, _report("anonymous", offenders)


async def test_customer_token_never_reaches_admin_routes() -> None:
    offenders = []
    async with api_client() as (c, maker, _main):
        headers, _other = await _customer(c, maker)
        for method, path, op in _bearer_ops():
            if not path.startswith("/api/v1/admin/"):
                continue
            status = await _status(c, method, _fill(path, op), headers)
            if status not in (401, 403) and f"customer-admin {method} {path}" not in ALLOWED:
                offenders.append(f"{method} {path} -> {status}")
    assert not offenders, _report("customer on /admin", offenders)


async def test_customer_token_cannot_touch_another_store() -> None:
    offenders = []
    async with api_client() as (c, maker, _main):
        headers, other_id = await _customer(c, maker)
        for method, path, op in _bearer_ops():
            if "{store_id}" not in path or path.startswith(("/api/v1/admin/", "/api/v1/reseller-api/")):
                continue
            status = await _status(c, method, _fill(path, op, other_id), headers)
            if status not in (401, 403, 404) and f"customer-store {method} {path}" not in ALLOWED:
                offenders.append(f"{method} {path} -> {status}")
    assert not offenders, _report("customer on another store", offenders)


# Operations that do not use the bearer scheme. Each is public by design or is authenticated by its own credential; a new entry
# here is a conscious, reviewed decision (the test below fails for anything not listed).
PUBLIC_BY_DESIGN: dict[str, str] = {
    "health": "/health /health/live /health/ready: liveness/readiness probes",
    "auth": "/api/v1/auth/*: sign-in, refresh, invite and Telegram login flows (the credentials are in the body; rate limited per IP)",
    "storefront": "/api/v1/stores/{main,by-domain,by-slug,store_id,...}: the public catalog",
    "button-styles": "/api/v1/telegram/button-styles: static bot UI configuration",
    "callbacks": "/api/v1/payments/callbacks/{provider}: the buyer's browser returns from the gateway; the payment is verified server-side",
    "bank-sms": "/api/v1/payments/bank-sms/{store_id}: per-store secret, checked by the handler",
    "reseller-api": "/api/v1/reseller-api/v1/*: X-API-Key (store-bound, scoped)",
    "internal": "/api/v1/internal/identity/telegram/status: called by the bots with the service credential",
}


def _public_ops() -> list[tuple[str, str]]:
    spec = app.openapi()
    return sorted(
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in _METHODS and not op.get("security")
    )


def _group(path: str) -> str:
    if path.startswith("/health"):
        return "health"
    if path.startswith("/api/v1/auth/"):
        return "auth"
    if path.startswith("/api/v1/stores/"):
        return "storefront"
    if path.startswith("/api/v1/telegram/button-styles"):
        return "button-styles"
    if path.startswith("/api/v1/payments/callbacks/"):
        return "callbacks"
    if path.startswith("/api/v1/payments/bank-sms/"):
        return "bank-sms"
    if path.startswith("/api/v1/reseller-api/"):
        return "reseller-api"
    if path.startswith("/api/v1/internal/"):
        return "internal"
    return "UNLISTED"


def test_the_operations_without_the_bearer_scheme_are_a_known_set() -> None:
    unlisted = [f"{m} {p}" for m, p in _public_ops() if _group(p) == "UNLISTED"]
    assert not unlisted, "new operation without the bearer scheme; add it to PUBLIC_BY_DESIGN with a reason: " + ", ".join(unlisted)
    # Guard against a vacuous matrix: the probes above only mean something while they actually cover the API.
    assert len(_bearer_ops()) > 300
    assert sum(1 for _m, p, _o in _bearer_ops() if p.startswith("/api/v1/admin/")) > 150


async def test_own_credential_endpoints_reject_a_missing_credential() -> None:
    """The riskiest public operations authenticate themselves (API key, bot service key, per-store SMS secret)."""
    offenders = []
    async with api_client() as (c, maker, _main):
        _headers, other_id = await _customer(c, maker)
        for method, path in _public_ops():
            group = _group(path)
            if group not in ("reseller-api", "bank-sms", "internal") and not path.startswith(
                ("/api/v1/auth/telegram/bot", "/api/v1/auth/telegram/link", "/api/v1/auth/telegram/web/bot/")
            ):
                continue
            op = {"parameters": [], **app.openapi()["paths"][path][method.lower()]}
            status = await _status(c, method, _fill(path, op, other_id), {})
            if status not in (401, 403) and f"no-credential {method} {path}" not in ALLOWED:
                offenders.append(f"{method} {path} -> {status}")
    assert not offenders, _report("missing credential", offenders)
