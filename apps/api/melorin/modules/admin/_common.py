"""Admin API -  common routes (split from the former 1,900-line router; paths unchanged)."""

import logging
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from melorin.core.errors import AppError

log = logging.getLogger("melorin.admin")


# ----- Safe deletion (products / panels / servers / sales bundles) -----
# Rule: an entity that already took part in a sale is never erased, because orders and VPN accounts keep
# pointing at it. Those are refused with 409 + a plain reason; the admin disables them instead.
# Anything nobody has used yet is removed for real. Nothing here talks to the remote VPN panel.
async def _count(session, model, *where) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def _names(rows, limit: int = 5) -> str:
    rows = list(rows)
    shown = "، ".join(f"«{x}»" for x in rows[:limit])
    return shown + (f" و {len(rows) - limit} مورد دیگر" if len(rows) > limit else "")


async def _commit_or_conflict(session, what: str) -> None:
    """A concurrent sale can reference the row between our check and the DELETE; the FK then protects it."""
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise AppError("IN_USE", f"{what} هم‌اکنون در حال استفاده است و حذف نشد. غیرفعال کنید.", 409) from e
