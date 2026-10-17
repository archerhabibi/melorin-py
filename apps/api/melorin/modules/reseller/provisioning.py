"""Creation of the reseller Store from an approved application (shared by admin review and the applicant's details step)."""

from melorin.modules.reseller.linking import link_store_catalog
from melorin.modules.stores.models import BotStoreBinding, ResellerApplication, ResellerProfile, Store, StoreMembership


async def create_reseller_store(session, a: ResellerApplication, target: Store, *, token_enc: str, debt_limit: int) -> Store:
    """Store + profile + owner membership + bot binding for ``a``. The caller commits and has already validated identity."""
    st = Store(
        kind="reseller",
        name=a.store_name,
        slug=f"reseller-{str(a.id)[:8]}",
        owner_user_id=a.user_id,
        parent_store_id=target.id,
        currency=target.currency,
        domain=a.domain,
        bot_token_enc=token_enc,
        bot_username=a.bot_username,
    )
    session.add(st)
    await session.flush()
    a.store_id = st.id
    session.add(ResellerProfile(store_id=st.id, user_id=a.user_id, debt_limit=debt_limit, api_enabled=True))
    session.add(StoreMembership(store_id=st.id, user_id=a.user_id, role="owner"))
    session.add(
        BotStoreBinding(
            bot_key=a.bot_key, bot_username=a.bot_username, store_id=st.id, owner_user_id=a.user_id, bot_kind="reseller", status="active"
        )
    )
    await link_store_catalog(session, st)  # connect the new store to the main packages and sales bundles
    return st
