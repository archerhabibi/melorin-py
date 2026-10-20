"""StoreScope: the ONE place that decides which customer-owned rows a caller may see or act on.

Rule (business, non-negotiable): a normal customer sees and manages ONLY the accounts, orders, payments and notifications
that belong to HIM **in the store he is currently using** (the store of the website / bot he is in). Whatever he bought in
another store or bot is invisible there and cannot be renewed from there; and nobody else's rows are ever reachable.

How it is enforced (defence in depth, all in Core, never in a channel):

* every customer endpoint lives under ``/stores/{store_id}/...`` and gets a :class:`StoreScope` built from the resolved
  ``StoreContext`` (so membership/suspension is checked first); there is no "all my stores" endpoint any more;
* queries never spell ``user_id``/``store_id`` by hand: they use ``scope.where(Model)`` (lists, counters, search) or
  ``scope.get(session, Model, id)`` (one row), so the pair can neither be forgotten nor half-applied;
* a row of another store or another user answers exactly like a row that does not exist (404), so ids cannot be probed.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import TYPE_CHECKING, Any

from melorin.core.errors import NotFound

if TYPE_CHECKING:  # pragma: no cover
    from melorin.core.deps import StoreContext


@dataclasses.dataclass(frozen=True)
class StoreScope:
    """``(store_id, user_id)``: the only pair of ids a customer-facing query may be built from."""

    store_id: uuid.UUID
    user_id: uuid.UUID

    @classmethod
    def of(cls, ctx: StoreContext) -> StoreScope:
        return cls(store_id=ctx.store.id, user_id=ctx.user.id)

    # ---- list / count / search ---------------------------------------------------------------
    def where(self, model: Any) -> tuple:
        """SQL conditions limiting ``model`` (needs ``user_id`` and ``store_id`` columns) to this customer in this store."""
        return (model.user_id == self.user_id, model.store_id == self.store_id)

    # ---- single rows -------------------------------------------------------------------------
    def owns(self, row: Any) -> bool:
        return row is not None and row.user_id == self.user_id and row.store_id == self.store_id

    def require(self, row: Any, what: str) -> Any:
        """Return ``row`` when it belongs to this customer in this store, otherwise behave as if it did not exist."""
        if not self.owns(row):
            raise NotFound(what)
        return row

    async def get(self, session, model: Any, row_id: uuid.UUID, what: str, **kw) -> Any:
        return self.require(await session.get(model, row_id, **kw), what)


@dataclasses.dataclass(frozen=True)
class OwnerScope:
    """What a reseller (store owner) may reach: rows of HIS OWN store only (never another store, never his other stores)."""

    store_id: uuid.UUID
    owner_id: uuid.UUID

    @classmethod
    def of(cls, ctx: StoreContext) -> OwnerScope:
        return cls(store_id=ctx.store.id, owner_id=ctx.user.id)

    def where(self, model: Any) -> tuple:
        return (model.store_id == self.store_id,)

    def own(self, model: Any) -> tuple:
        """The owner's personal rows: his, and in this store only."""
        return (model.user_id == self.owner_id, model.store_id == self.store_id)
