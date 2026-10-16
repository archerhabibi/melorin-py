import re
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from melorin.core.db import Base, IdMixin, TimestampMixin


class PanelGroup(IdMixin, TimestampMixin, Base):
    """A sellable pool of panels with routing, naming and quota policy."""

    __tablename__ = "panel_groups"
    name: Mapped[str] = mapped_column(String(120))
    selection_mode: Mapped[str] = mapped_column(String(20), default="automatic")  # automatic | manual
    naming_mode: Mapped[str] = mapped_column(String(20), default="automatic")  # automatic | custom
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reseller_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sales_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sold_count: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict | None] = mapped_column(JSON)


class PanelGroupMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "panel_group_members"
    __table_args__ = (UniqueConstraint("panel_group_id", "panel_id"),)
    panel_group_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panel_groups.id", ondelete="CASCADE"), index=True)
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id"), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sales_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sold_count: Mapped[int] = mapped_column(Integer, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class StorePanelGroup(IdMixin, TimestampMixin, Base):
    __tablename__ = "store_panel_groups"
    __table_args__ = (UniqueConstraint("store_id", "panel_group_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    panel_group_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panel_groups.id", ondelete="CASCADE"), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


def clean_custom_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", value or "")[:40]
