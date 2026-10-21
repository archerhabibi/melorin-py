"""Renewal on behalf of a customer, started by the reseller who owns the store.

The account search/scope rules stay in :mod:`melorin.modules.vpn.inquiry`; the renewal itself runs through the same
orders/catalog rules a customer would hit, so this file only wires them together for the reseller channel."""

import uuid

from melorin.core import audit
from melorin.core.deps import resolve_store_context
from melorin.kernel.models.vpn import VpnAccount
from melorin.modules.catalog.router import renewal_info
from melorin.modules.orders import service as orders
from melorin.modules.reseller.schemas import OwnerRenewalOut
from melorin.modules.vpn import inquiry

PAYER_NOTE = "مبلغ از کیف پول صاحب اکانت در همین فروشگاه کسر می‌شود."


async def holder_context(session, account: VpnAccount, holder):
    """The holder's own context in the store the account lives in: a renewal then runs through exactly the same core
    rules as one started by the holder himself (ownership, window, package, price, wallet)."""
    return await resolve_store_context(session, account.store_id, holder)


async def reseller_renewal_offer(session, owner_id: uuid.UUID, store_id: uuid.UUID, account_id: uuid.UUID):
    """What renewing this account would be: the answer the holder would get, plus who pays."""
    account, holder = await inquiry.reseller_find(session, owner_id, store_id, account_id)
    offer = (await renewal_info(account.id, await holder_context(session, account, holder), session)).model_dump()
    return OwnerRenewalOut(**offer, payer_note=None if account.user_id == owner_id else PAYER_NOTE)


async def reseller_renew(session, owner_id: uuid.UUID, store_id: uuid.UUID, account_id: uuid.UUID, *, idempotency_key: str, channel: str):
    """Renew one of the reseller's OWN accounts or one of THIS store's customers' accounts with the account's own package at
    its current price. The order belongs to the account's holder and is paid from the holder's wallet in the store; every
    renewal rule stays in :mod:`renewal` / ``orders.create_order``. Returns the order."""
    account, holder = await inquiry.reseller_find(session, owner_id, store_id, account_id)
    product_id, is_own = account.product_id, account.user_id == owner_id
    order = await orders.create_order(
        session,
        await holder_context(session, account, holder),
        product_id=product_id,
        idempotency_key=idempotency_key,
        kind="renewal",
        vpn_account_id=account_id,
        channel=channel,
    )
    if not is_own:
        audit.record(
            session,
            "order.renewed_by_owner",
            actor_id=owner_id,
            entity_type="order",
            entity_id=order.id,
            store_id=order.store_id,
            data={"vpn_account_id": str(account_id), "customer_id": str(order.user_id)},
        )
        await session.commit()
    return order
