import hashlib
import ipaddress
import secrets


from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.modules.stores.models import ApiCredential, Store

ALLOWED_SCOPES = {"catalog:read", "customers:read", "customers:wallet:write", "orders:read", "wallet:read", "reports:read"}
PREFIX = "mln_live_"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _raw() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def out(c: ApiCredential) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "key_prefix": c.key_prefix,
        "scopes": c.scopes,
        "status": c.status,
        "rate_limit_per_minute": c.rate_limit_per_minute,
        "ip_allowlist": c.ip_allowlist,
        "expires_at": c.expires_at,
        "last_used_at": c.last_used_at,
        "created_at": c.created_at,
    }


def validate_scopes(scopes: list[str]) -> list[str]:
    if not scopes or not set(scopes) <= ALLOWED_SCOPES:
        raise AppError("API_SCOPE_INVALID", "دسترسی API نامعتبر است.", 400, {"allowed": sorted(ALLOWED_SCOPES)})
    return sorted(set(scopes))


def validate_ips(values: list[str] | None) -> list[str] | None:
    try:
        for value in values or []:
            ipaddress.ip_network(value, strict=False)
    except ValueError as e:
        raise AppError("API_IP_INVALID", "محدودیت IP نامعتبر است.", 400) from e
    return values


async def create(session, store: Store, actor, body):
    raw = _raw()
    c = ApiCredential(
        store_id=store.id,
        name=body.name,
        key_prefix=raw[:16],
        key_hash=hash_key(raw),
        scopes=validate_scopes(body.scopes),
        status="active" if body.activate else "disabled",
        rate_limit_per_minute=body.rate_limit_per_minute,
        ip_allowlist=validate_ips(body.ip_allowlist),
        created_by=actor.id,
        expires_at=body.expires_at,
    )
    session.add(c)
    audit.record(
        session,
        "api_credential.created",
        actor_id=actor.id,
        actor_type="reseller",
        entity_type="api_credential",
        entity_id=c.id,
        store_id=store.id,
        data={"scopes": c.scopes},
    )
    await session.commit()
    return c, raw


async def rotate(session, c: ApiCredential, actor):
    if c.status == "revoked":
        raise AppError("API_KEY_REVOKED", "این کلید قابل چرخش نیست.", 409)
    c.status = "revoked"
    c.revoked_at = utcnow()
    raw = _raw()
    new = ApiCredential(
        store_id=c.store_id,
        name=c.name,
        key_prefix=raw[:16],
        key_hash=hash_key(raw),
        scopes=c.scopes,
        status="active",
        rate_limit_per_minute=c.rate_limit_per_minute,
        ip_allowlist=c.ip_allowlist,
        created_by=actor.id,
        rotated_from_id=c.id,
        expires_at=c.expires_at,
    )
    session.add(new)
    audit.record(
        session,
        "api_credential.rotated",
        actor_id=actor.id,
        actor_type="reseller",
        entity_type="api_credential",
        entity_id=c.id,
        store_id=c.store_id,
    )
    await session.commit()
    return new, raw


async def set_status(session, c: ApiCredential, status: str, actor):
    if status not in ("activate", "disable", "revoke"):
        raise AppError("API_ACTION_INVALID", "عملیات کلید API نامعتبر است.", 400)
    c.status = {"activate": "active", "disable": "disabled", "revoke": "revoked"}[status]
    if status == "revoke":
        c.revoked_at = utcnow()
    audit.record(
        session,
        "api_credential.status_changed",
        actor_id=actor.id,
        actor_type="reseller",
        entity_type="api_credential",
        entity_id=c.id,
        store_id=c.store_id,
        data={"status": c.status},
    )
    await session.commit()


# Authenticating a key (and binding it to its store) is Core's job: see ``melorin.core.channel.api_channel``.
