"""Per-store payment destination: the ONE model (``StorePaymentConfiguration``) for the main store and every reseller store.

Before this module the main store used global settings (``card.info``, ``gateway.zarinpal``) with a fallback in
``service.store_payment_settings``. That fallback is gone: the main store is a store like any other. ``legacy_rows`` converts the old
global values once (alembic 0056); after that nobody reads or writes them.
"""

import json
import uuid
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError, field_validator
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


class ZarinpalSecretIn(BaseModel):
    """Write-only Zarinpal credentials. ``access_token`` (needed only for refunds) follows three explicit rules:

    omitted / blank -> keep the stored token; non-blank -> replace it; ``clear_access_token`` -> delete it.
    A blank password field is never read as a deletion, and replace + delete in one request is ambiguous, so it is refused.
    """

    model_config = ConfigDict(extra="forbid")

    merchant_id: StrictStr = Field(max_length=128)
    access_token: StrictStr | None = Field(default=None, max_length=2048)
    clear_access_token: StrictBool = False

    @field_validator("merchant_id")
    @classmethod
    def _merchant_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("merchant_id is required")
        return v

    @field_validator("access_token")
    @classmethod
    def _token_trimmed(cls, v: str | None) -> str | None:
        return (v or "").strip() or None  # blank == not provided

    def merged_with(self, stored: Mapping[str, object]) -> dict:
        if self.clear_access_token and self.access_token:
            raise ValueError("send either access_token or clear_access_token, not both")
        out: dict = {"merchant_id": self.merchant_id}
        token = None if self.clear_access_token else (self.access_token or stored.get("access_token"))
        if token:
            out["access_token"] = token
        return out


def _zarinpal_secret(secret: Mapping[str, object], stored: Mapping[str, object]) -> dict:
    try:
        return ZarinpalSecretIn.model_validate(dict(secret)).merged_with(stored)
    except (ValidationError, ValueError) as exc:
        raise AppError(
            "PAYMENT_CONFIG_INVALID",
            "اطلاعات محرمانهٔ زرین‌پال نامعتبر است (Merchant ID الزامی است و فقط یکی از «جایگزینی توکن» یا «حذف توکن» مجاز است).",
            422,
        ) from exc


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
        # Only the *presence* of the refund token is ever exposed, never its value.
        out["has_access_token"] = bool(secret.get("access_token"))
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

    Zarinpal secrets are validated by ``ZarinpalSecretIn``: editing the merchant id keeps a stored access token, and the token
    is replaced or deleted only on an explicit request.
    """
    from melorin.modules.payments.adapters.registry import get_adapter

    get_adapter(provider)  # unknown provider -> the registry's own error
    row = await session.scalar(
        select(StorePaymentConfiguration).where(
            StorePaymentConfiguration.store_id == store_id, StorePaymentConfiguration.provider == provider
        )
    )
    # Validate and build the new secret BEFORE touching the row, so a refused request leaves nothing half-applied.
    secret_changed = secret is not None
    new_secret = None
    token_changed = False
    if secret is not None:
        if provider == "zarinpal":
            stored = json.loads(decrypt(row.secret_enc) or "{}") if row is not None and row.secret_enc else {}
            new_secret = _zarinpal_secret(secret, stored)
            token_changed = new_secret.get("access_token") != stored.get("access_token")
        else:
            new_secret = secret
    if row is None:
        row = StorePaymentConfiguration(store_id=store_id, provider=provider)
        session.add(row)
    row.is_enabled, row.public_config, row.updated_by = is_enabled, public_config, actor_id
    if new_secret is not None:
        row.secret_enc = encrypt(json.dumps(new_secret))
    audit.record(
        session,
        "store.payment_config_updated",
        actor_id=actor_id,
        actor_type=actor_type,
        entity_type="store",
        entity_id=store_id,
        store_id=store_id,
        data={"provider": provider, "enabled": is_enabled, "secret_changed": secret_changed, "access_token_changed": token_changed},
    )
    return row


def require_main_store_provider(provider: str) -> None:
    if provider not in MAIN_STORE_PROVIDERS:
        raise AppError("PAYMENT_PROVIDER_UNSUPPORTED", "این روش برای فروشگاه اصلی قابل تنظیم نیست.", 400)
