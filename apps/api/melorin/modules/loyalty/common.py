"""Loyalty club: common (see ``service.py`` for the facade and the overview)."""

import datetime as dt
import uuid


from melorin.core.errors import AppError
from melorin.domain.loyalty import LoyaltyError


HISTORY_MAX = 100


_REVERSIBLE = ("order_earn", "first_order_bonus", "referral_bonus")  # earnings that belong to an order and go back with it


def _fail(e: LoyaltyError) -> AppError:
    return AppError(e.code, e.message, 400)


def _json(d: dict | None) -> dict | None:
    return None if d is None else {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in d.items()}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
