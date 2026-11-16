"""Bank SMS auto-verification: config (see ``bank_sms/__init__.py`` for the overall flow)."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.errors import AppError
from melorin.domain import bank_sms as dom
from melorin.kernel.models.payments import BankSmsSource


log = logging.getLogger("melorin.payments.bank_sms")


MAX_SMS_CHARS = 1000


TOKEN_PREFIX = "mlr_sms_"


# (key, kind, minimum, maximum, default) - the single place that defines which tuning knobs exist.
_SETTING_RULES: tuple[tuple[str, type, Any, Any, Any], ...] = (
    ("window_minutes", int, 5, 7 * 24 * 60, 720),
    ("time_tolerance_minutes", int, 0, 30, 5),
    ("require_claimed_time", bool, None, None, True),
    ("max_auto_amount_rial", int, 1, 10**13, None),
    ("account_number", str, 8, 26, None),
)


def clean_settings(raw: dict | None) -> dict:
    """Validate the tuning knobs (ordered rule table); unknown keys are rejected, ``None`` resets to the default."""
    raw = dict(raw or {})
    out: dict = {}
    for key, kind, lo, hi, _default in _SETTING_RULES:
        if key not in raw:
            continue
        value = raw.pop(key)
        if value is None:
            continue
        if kind is bool:
            if not isinstance(value, bool):
                raise AppError("BANK_SMS_SETTING_INVALID", f"مقدار «{key}» باید درست/نادرست باشد.", 422)
        elif kind is str:
            value = dom.digits_only(value) if isinstance(value, str) else ""
            if not (lo <= len(value) <= hi):
                raise AppError("BANK_SMS_SETTING_INVALID", "شماره حساب باید فقط عدد و بین ۸ تا ۲۶ رقم باشد.", 422)
        else:
            if isinstance(value, bool) or not isinstance(value, int) or not (lo <= value <= hi):
                raise AppError("BANK_SMS_SETTING_INVALID", f"مقدار «{key}» باید عددی بین {lo} و {hi} باشد.", 422)
        out[key] = value
    if raw:
        raise AppError("BANK_SMS_SETTING_INVALID", f"تنظیم ناشناخته: {', '.join(sorted(raw))}", 422)
    return out


def match_settings(source: BankSmsSource) -> dom.MatchSettings:
    s = source.settings or {}
    return dom.MatchSettings(
        window_minutes=int(s.get("window_minutes", 720)),
        time_tolerance_minutes=int(s.get("time_tolerance_minutes", 5)),
        require_claimed_time=bool(s.get("require_claimed_time", True)),
        max_auto_amount_rial=s.get("max_auto_amount_rial"),
    )


def source_out(src: BankSmsSource | None, *, store_id: uuid.UUID | None = None) -> dict:
    s = src.settings if src else {}
    return {
        "store_id": str(src.store_id if src else store_id),
        "configured": src is not None,
        "bank": src.bank if src else "mehr_iran",
        "is_enabled": src.is_enabled if src else False,
        "auto_verify": src.auto_verify if src else False,
        "has_token": bool(src and src.token_hash),
        "token_hint": src.token_hint if src else None,
        "senders": list(src.senders or []) if src else [],
        "settings": {
            "window_minutes": (s or {}).get("window_minutes", 720),
            "time_tolerance_minutes": (s or {}).get("time_tolerance_minutes", 5),
            "require_claimed_time": (s or {}).get("require_claimed_time", True),
            "max_auto_amount_rial": (s or {}).get("max_auto_amount_rial"),
            "account_number": (s or {}).get("account_number"),
        },
        "last_received_at": src.last_received_at if src else None,
    }


# ------------------------------------------------------------------------------------------------ configuration
async def get_source(session: AsyncSession, store_id: uuid.UUID) -> BankSmsSource | None:
    return await session.scalar(select(BankSmsSource).where(BankSmsSource.store_id == store_id))
