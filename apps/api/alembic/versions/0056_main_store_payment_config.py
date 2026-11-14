"""Main store payment destination moves to the per-store model (docs/DECISIONS.md, architecture review 2026-11-13).

The old global settings ``card.info`` and ``gateway.zarinpal`` become ``store_payment_configurations`` rows of the main store (only when
the destination is complete and the row does not exist yet), and the old setting rows are deleted. Forward-only: the downgrade keeps the
new rows (restoring the global settings would resurrect the removed fallback).
"""

from alembic import op
from sqlalchemy import select
from sqlalchemy.orm import Session

revision = "0056_main_store_payment_config"
down_revision = "0055_admin_team"
branch_labels = None
depends_on = None


def upgrade() -> None:
    import json

    from melorin.core.crypto import encrypt
    from melorin.kernel.models.stores import Store, StorePaymentConfiguration
    from melorin.kernel.models.system import SystemSetting
    from melorin.modules.payments.store_config import LEGACY_KEYS, legacy_rows

    session = Session(bind=op.get_bind())
    try:
        rows = {r.key: r for r in session.scalars(select(SystemSetting).where(SystemSetting.key.in_(LEGACY_KEYS))).all()}
        store = session.scalar(select(Store).where(Store.kind == "main"))
        if store is not None:
            for provider, public, secret in legacy_rows({k: r.value for k, r in rows.items()}):
                exists = session.scalar(
                    select(StorePaymentConfiguration.id).where(
                        StorePaymentConfiguration.store_id == store.id, StorePaymentConfiguration.provider == provider
                    )
                )
                if exists is None:
                    session.add(
                        StorePaymentConfiguration(
                            store_id=store.id,
                            provider=provider,
                            is_enabled=True,
                            public_config=public,
                            secret_enc=encrypt(json.dumps(secret)) if secret else None,
                        )
                    )
        for r in rows.values():
            session.delete(r)
        session.flush()
    finally:
        session.close()


def downgrade() -> None:
    pass
