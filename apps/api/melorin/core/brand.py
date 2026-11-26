"""Product name vs. store name (docs/06 ADR-R3).

``Melorin`` is the name of the PLATFORM: this software, its admin panel and its operators' documentation. It is **not** the
name of any store. The main store and every reseller store are called whatever their owner chooses, and that name is the
brand a customer sees on the website, in e-mails and on the payment page. Nothing in Core may assume a store is called
Melorin; code that talks to a *customer* asks this module for the store's name, and only falls back to the product name when
no store can be determined at all (for example a request from a host Core does not know).

Platform-operator surfaces (the admin panel, admin invitations, the admin's TOTP issuer) keep the product name on purpose:
they belong to the platform, not to a store.
"""

from __future__ import annotations

import unicodedata
import uuid
from typing import Any

from sqlalchemy import select

from melorin.core.errors import AppError

PRODUCT_NAME = "Melorin"
# What the first bootstrap calls the main store when the operator gave no name. The admin panel already labels ``kind == "main"``
# stores with this phrase, so the default reads the same everywhere. It is a label, not a brand: rename it in the admin panel.
DEFAULT_MAIN_STORE_NAME = "فروشگاه اصلی"
STORE_NAME_MAX = 200  # ``stores.name`` is String(200)


def normalize_store_name(raw: str | None) -> str:
    """The one validation of a store name (bootstrap, admin rename). Raises ``ValueError`` with a Persian reason.

    Whitespace (including newlines and tabs) collapses to single spaces; control characters are refused. Zero-width
    non-joiners are format characters, not control characters, and stay: Persian words need them.
    """
    name = " ".join((raw or "").split())
    if not name:
        raise ValueError("نام فروشگاه نباید خالی باشد.")
    if len(name) > STORE_NAME_MAX:
        raise ValueError(f"نام فروشگاه نباید بیشتر از {STORE_NAME_MAX} نویسه باشد.")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise ValueError("نام فروشگاه نباید نویسهٔ کنترلی داشته باشد.")
    return name


def brand_or_product(name: str | None) -> str:
    """A store name for customer-facing text; the product name only when there is no store name to use."""
    return " ".join((name or "").split()) or PRODUCT_NAME


async def store_brand(session: Any, store_id: uuid.UUID | None) -> str:
    """The name of ``store_id`` for customer-facing text (e-mail subjects, gateway descriptions)."""
    if store_id is None:
        return PRODUCT_NAME
    from melorin.kernel.models.stores import Store

    return brand_or_product(await session.scalar(select(Store.name).where(Store.id == store_id)))


async def site_brand(session: Any, request: Any) -> str:
    """The brand of the store whose website ``request`` came through. Never raises.

    ``channel.site_channel`` refuses an unknown host in production. That refusal belongs to the endpoints that open a session
    (they still call it); a mail subject must not turn a harmless request into an error, so here an unresolvable store simply
    means the product name.
    """
    from melorin.core import channel

    try:
        site = await channel.site_channel(session, request)
    except AppError:
        return PRODUCT_NAME
    return await store_brand(session, site.store_id)
