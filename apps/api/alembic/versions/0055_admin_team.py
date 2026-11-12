"""Admin team: roles for every admin and one-time invitations for new ones (docs/24-Admin-Team-Design.md).

* ``admin_invites``  hashed one-time invite tokens; the invitee sets their own password and authenticator.
* ``users.admin_roles``  every existing admin becomes ``["owner"]`` (before this migration an admin could do everything), so nobody
  loses access on upgrade. From now on an admin with an empty role list has no access (fail closed).

Additive: no existing column or row changes meaning except the explicit owner back-fill.
"""

import sqlalchemy as sa
from alembic import op

revision = "0055_admin_team"
down_revision = "0054_sold_vs_now"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_admin_invites_token_hash"),
    )
    op.create_index("ix_admin_invites_user_id", "admin_invites", ["user_id"])
    op.create_index("ix_admin_invites_expires_at", "admin_invites", ["expires_at"])
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE users SET admin_roles = :roles WHERE is_super_admin = :yes").bindparams(
            sa.bindparam("roles", type_=sa.JSON()), sa.bindparam("yes", type_=sa.Boolean())
        ),
        {"roles": ["owner"], "yes": True},
    )


def downgrade() -> None:
    op.drop_index("ix_admin_invites_expires_at", table_name="admin_invites")
    op.drop_index("ix_admin_invites_user_id", table_name="admin_invites")
    op.drop_table("admin_invites")
