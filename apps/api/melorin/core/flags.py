"""Emergency controls / maintenance. Nothing is hard-coded: flags live in DB and are audited."""
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.errors import AppError
from melorin.modules.system.models import FeatureFlag

KEYS = ["system", "purchase", "payment", "provisioning", "reseller_sales", "api", "bot", "test_account", "registration"]


async def is_enabled(session: AsyncSession, key: str, *, store_id=None, channel: str | None = None) -> bool:
    scopes = [(FeatureFlag.scope_type == "global")]
    if store_id is not None:
        scopes.append((FeatureFlag.scope_type == "store") & (FeatureFlag.scope_id == str(store_id)))
    if channel:
        scopes.append((FeatureFlag.scope_type == "channel") & (FeatureFlag.scope_id == channel))
    q = select(FeatureFlag.id).where(
        FeatureFlag.key.in_([key, "system"]), FeatureFlag.enabled.is_(False), or_(*scopes)
    )
    return (await session.scalar(q.limit(1))) is None


async def ensure_enabled(session: AsyncSession, key: str, *, store_id=None, channel: str | None = None) -> None:
    if not await is_enabled(session, key, store_id=store_id, channel=channel):
        raise AppError("FEATURE_DISABLED", "این قابلیت موقتاً غیرفعال است. لطفاً بعداً تلاش کنید.", 503, {"feature": key})
