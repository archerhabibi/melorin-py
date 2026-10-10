"""Scope reseller applications and stores to a parent store.

Revision ID: 0006_store_scoped_resellers
Revises: 0005_orders_vpn_fk
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_store_scoped_resellers"
down_revision = "0005_orders_vpn_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    store_columns = {c["name"] for c in inspector.get_columns("stores")}
    if "parent_store_id" not in store_columns:
        op.add_column("stores", sa.Column("parent_store_id", sa.Uuid(), nullable=True))
        op.create_foreign_key("fk_stores_parent_store_id_stores", "stores", "stores", ["parent_store_id"], ["id"])
        op.create_index("ix_stores_parent_store_id", "stores", ["parent_store_id"])

    app_columns = {c["name"] for c in inspector.get_columns("reseller_applications")}
    if "target_store_id" not in app_columns:
        op.add_column("reseller_applications", sa.Column("target_store_id", sa.Uuid(), nullable=True))
        op.create_foreign_key("fk_reseller_applications_target_store_id_stores", "reseller_applications", "stores", ["target_store_id"], ["id"])
        main_id = bind.execute(sa.text("SELECT id FROM stores WHERE kind = 'main' ORDER BY created_at LIMIT 1")).scalar()
        if main_id:
            bind.execute(sa.text("UPDATE reseller_applications SET target_store_id = :main WHERE target_store_id IS NULL"), {"main": main_id})
        op.alter_column("reseller_applications", "target_store_id", nullable=False)
        old = {i["name"] for i in inspector.get_indexes("reseller_applications")}
        if "uq_reseller_application_pending_user" in old:
            op.drop_index("uq_reseller_application_pending_user", table_name="reseller_applications")
        op.create_index(
            "uq_reseller_application_pending_user_store",
            "reseller_applications",
            ["user_id", "target_store_id"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        )
    # Existing reseller stores were all created from Main Store in v1.1.
    bind.execute(sa.text("""
        UPDATE stores AS child
        SET parent_store_id = main.id
        FROM stores AS main
        WHERE child.kind = 'reseller' AND child.parent_store_id IS NULL AND main.kind = 'main'
    """))


def downgrade() -> None:
    op.drop_index("uq_reseller_application_pending_user_store", table_name="reseller_applications")
    op.drop_constraint("fk_reseller_applications_target_store_id_stores", "reseller_applications", type_="foreignkey")
    op.drop_column("reseller_applications", "target_store_id")
    op.drop_index("ix_stores_parent_store_id", table_name="stores")
    op.drop_constraint("fk_stores_parent_store_id_stores", "stores", type_="foreignkey")
    op.drop_column("stores", "parent_store_id")
