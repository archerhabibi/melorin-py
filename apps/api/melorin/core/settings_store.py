"""Runtime business settings stored in DB (admin-editable), with safe defaults."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.modules.system.models import SystemSetting

DEFAULTS: dict[str, object] = {
    "referral.signup_reward": 0,
    "referral.commission_bp": 500,  # 5% in basis points
    "test.enabled": True,
    "test.product_code": "TEST",
    "test.max_per_user": 1,
    "test.cooldown_hours": 720,
    "provisioning.max_attempts": 5,
    "provisioning.backoff_seconds": [15, 60, 300, 900, 1800],
    "card.info": {"card_number": "", "holder": "", "bank": ""},
    "debt.near_ratio": 0.8,
    "vpn.near_expiry_hours": 48,
    "terms.version": "1.0",
    "backup.retention_days": 30,
    "backup.runs_per_day": 1,
    "privacy.verification_code_retention_days": 7,
}


async def get(session: AsyncSession, key: str):
    v = await session.scalar(select(SystemSetting.value).where(SystemSetting.key == key))
    return DEFAULTS.get(key) if v is None else v


async def set_value(session: AsyncSession, key: str, value) -> None:
    row = await session.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row:
        row.value = value
    else:
        session.add(SystemSetting(key=key, value=value))


async def all_settings(session: AsyncSession) -> dict:
    rows = (await session.scalars(select(SystemSetting))).all()
    out = dict(DEFAULTS)
    out.update({r.key: r.value for r in rows})
    return out
