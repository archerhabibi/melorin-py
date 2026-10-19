"""Merge legacy ``reseller_credit`` wallets into the owner's ordinary Main Store wallet.

A reseller now uses the very same wallet they had as a customer; ``debt_limit`` is the only addition.
History stays append-only: each non-zero legacy balance is moved with a balanced ledger transaction.
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0026_merge_reseller_credit"
down_revision = "0025_reseller_bot_runtime"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    meta = sa.MetaData()
    U = sa.Uuid
    w = sa.Table(
        "wallets", meta, sa.Column("id", U, primary_key=True), sa.Column("user_id", U), sa.Column("store_id", U),
        sa.Column("kind", sa.String), sa.Column("currency", sa.String), sa.Column("balance", sa.BigInteger),
    )
    tx = sa.Table(
        "ledger_transactions", meta, sa.Column("id", U, primary_key=True), sa.Column("kind", sa.String),
        sa.Column("idempotency_key", sa.String), sa.Column("store_id", U), sa.Column("currency", sa.String), sa.Column("memo", sa.String),
    )
    en = sa.Table(
        "ledger_entries", meta, sa.Column("id", U, primary_key=True), sa.Column("transaction_id", U), sa.Column("account", sa.String),
        sa.Column("wallet_id", U), sa.Column("amount", sa.BigInteger), sa.Column("balance_after", sa.BigInteger),
    )
    # Row locks keep the merge consistent if the API is still serving traffic while the migration runs (no-op on SQLite).
    legacy = bind.execute(sa.select(w).where(w.c.kind == "reseller_credit").order_by(w.c.id).with_for_update()).mappings().all()
    for old in legacy:
        target = bind.execute(
            sa.select(w).where(w.c.user_id == old["user_id"], w.c.store_id == old["store_id"], w.c.kind == "customer", w.c.currency == old["currency"]).with_for_update()
        ).mappings().first()
        if target is None:
            tid = uuid.uuid4()
            bind.execute(sa.insert(w).values(id=tid, user_id=old["user_id"], store_id=old["store_id"], kind="customer", currency=old["currency"], balance=0))
            target_balance = 0
        else:
            tid, target_balance = target["id"], target["balance"]
        amount = old["balance"]
        if amount != 0:
            txid = uuid.uuid4()
            bind.execute(
                sa.insert(tx).values(
                    id=txid, kind="wallet_merge", idempotency_key=f"migration:0026:{old['id']}", store_id=old["store_id"],
                    currency=old["currency"], memo="ادغام کیف پول اعتباری نمایندگی در کیف پول اصلی",
                )
            )
            bind.execute(sa.insert(en).values(id=uuid.uuid4(), transaction_id=txid, account=f"wallet:{old['id']}", wallet_id=old["id"], amount=-amount, balance_after=0))
            bind.execute(sa.insert(en).values(id=uuid.uuid4(), transaction_id=txid, account=f"wallet:{tid}", wallet_id=tid, amount=amount, balance_after=target_balance + amount))
            bind.execute(sa.update(w).where(w.c.id == old["id"]).values(balance=0))
            bind.execute(sa.update(w).where(w.c.id == tid).values(balance=target_balance + amount))


def downgrade():
    # Irreversible by design: merged balances stay in the customer wallet (the ledger keeps the full history).
    pass
