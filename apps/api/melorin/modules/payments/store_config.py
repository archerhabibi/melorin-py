"""Per-store payment destination: the ONE model (``StorePaymentConfiguration``) for the main store and every reseller store.

Before this module the main store used global settings (``card.info``, ``gateway.zarinpal``) with a fallback in
``service.store_payment_settings``. That fallback is gone: the main store is a store like any other. ``legacy_rows`` converts the old
global values once (alembic 0056); after that nobody reads or writes them.
"""

import json
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.crypto import decrypt, encrypt
from melorin.core.errors import AppError
from melorin.kernel.models.stores import StorePaymentConfiguration

# Providers whose destination the admin may edit for the main store.
MAIN_STORE_PROVIDERS = ("manual_card", "zarinpal")
# Settings keys that used to hold the main store's destination. They are reserved now (the admin API refuses to write them).
LEGACY_KEYS = ("card.info", "gateway.zarinpal")
LEGACY_PREFIXES = ("card.", "gateway.", "destination.")
_CARD_FIELDS = ("card_number", "holder", "bank")


def is_legacy_key(key: str) -> bool:
    return key.startswith(LEGACY_PREFIXES)


def legacy_rows(settings: Mapping[str, object]) -> list[tuple[str, dict, dict]]:
    """Pure conversion of the old global values to ``(provider, public_config, secret)``; incomplete destinations are skipped."""
    out: list[tuple[str, dict, dict]] = []
    card = settings.get("card.info")
    if isinstance(card, dict) and card.get("card_number") and card.get("holder"):
        out.append(("manual_card", {k: card.get(k, "") for k in _CARD_FIELDS}, {}))
    zp = settings.get("gateway.zarinpal")
    if isinstance(zp, dict) and zp.get("merchant_id"):
        secret = {k: zp[k] for k in ("merchant_id", "access_token") if zp.get(k)}
        out.append(("zarinpal", {"sandbox": bool(zp.get("sandbox"))}, secret))
    return out


def admin_view(row: StorePaymentConfiguration) -> dict:
    """What the admin screen shows: secrets stay write-only, except the Zarinpal merchant id (an identifier, not a credential)."""
    secret = json.loads(decrypt(row.secret_enc) or "{}") if row.secret_enc else {}
    out = {
        "provider": row.provider,
        "is_enabled": row.is_enabled,
        "public_config": row.public_config or {},
        "has_secret": bool(row.secret_enc),
    }
    if row.provider == "zarinpal":
        out["merchant_id"] = secret.get("merchant_id", "")
    return out


async def list_configs(session: AsyncSession, store_id: uuid.UUID) -> list[StorePaymentConfiguration]:
    return list((await session.scalars(select(StorePaymentConfiguration).where(StorePaymentConfiguration.store_id == store_id))).all())


async def upsert(
    session: AsyncSession,
    *,
    store_id: uuid.UUID,
    provider: str,
    is_enabled: bool,
    public_config: dict,
    secret: dict | None,
    actor_id: uuid.UUID,
    actor_type: str,
) -> StorePaymentConfiguration:
    """Create or replace one destination and audit it. ``secret=None`` keeps the stored secret; the caller commits.

    A Zarinpal update that sends only a merchant id keeps a stored access token, so editing the id never silently drops it.
    """
    from melorin.modules.payments.adapters.registry import get_adapter

    get_adapter(provider)  # unknown provider -> the registry's own error
    row = await session.scalar(
        select(StorePaymentConfiguration).where(
            StorePaymentConfiguration.store_id == store_id, StorePaymentConfiguration.provider == provider
        )
    )
    if row is None:
        row = StorePaymentConfiguration(store_id=store_id, provider=provider)
        session.add(row)
    row.is_enabled, row.public_config, row.updated_by = is_enabled, public_config, actor_id
    if secret is not None:
        if provider == "zarinpal" and row.secret_enc:
            old = json.loads(decrypt(row.secret_enc) or "{}")
            secret = {**{k: v for k, v in old.items() if k == "access_token"}, **secret}
        row.secret_enc = encrypt(json.dumps(secret))
    audit.record(
        session,
        "store.payment_config_updated",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="store",
        entity_id=store_id,
        store_id=store_id,
        data={"provider": provider, "enabled": is_enabled, "secret_changed": secret is not None},
    )
    return row


def require_main_store_provider(provider: str) -> None:
    if provider not in MAIN_STORE_PROVIDERS:
        raise AppError("PAYMENT_PROVIDER_UNSUPPORTED", "این روش برای فروشگاه اصلی قابل تنظیم نیست.", 400)
