import uuid

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, IdMixin, TimestampMixin


class Bundle(IdMixin, TimestampMixin, Base):
    """A sales bundle (UI name: بسته فروش): panels + connection kind + routing, naming and quota policy.

    The table keeps its historical name ``bundles``; only the customer/admin vocabulary changed.
    """

    __tablename__ = "bundles"
    name: Mapped[str] = mapped_column(String(120))
    selection_mode: Mapped[str] = mapped_column(String(20), default="automatic")  # automatic | manual
    naming_mode: Mapped[str] = mapped_column(String(20), default="automatic")  # automatic | custom
    kind_label: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )  # free-text badge the customer sees next to the bundle name (admin decides)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reseller_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sales_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sold_count: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict | None] = mapped_column(JSON)


class BundleMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "bundle_members"
    __table_args__ = (UniqueConstraint("bundle_id", "panel_id"),)
    bundle_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bundles.id", ondelete="CASCADE"), index=True)
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id"), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sales_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sold_count: Mapped[int] = mapped_column(Integer, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )  # what a customer sees in a manual bundle (never the panel's own name)


class BundleProduct(IdMixin, TimestampMixin, Base):
    """A package sold inside a bundle. NULL prices fall back to the product's own prices, so a bundle only overrides what differs."""

    __tablename__ = "bundle_products"
    __table_args__ = (UniqueConstraint("bundle_id", "product_id"),)
    bundle_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bundles.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id", ondelete="CASCADE"), index=True)
    main_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reseller_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_listed: Mapped[bool] = mapped_column(Boolean, default=True)  # False = hidden from customers in this bundle
    sort: Mapped[int] = mapped_column(Integer, default=0)


class StoreBundle(IdMixin, TimestampMixin, Base):
    __tablename__ = "store_bundles"
    __table_args__ = (UniqueConstraint("store_id", "bundle_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    bundle_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bundles.id", ondelete="CASCADE"), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
