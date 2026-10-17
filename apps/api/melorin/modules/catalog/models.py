import datetime as dt
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from melorin.core.db import Base, CreatedMixin, IdMixin, TimestampMixin


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "products"
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    duration_days: Mapped[int] = mapped_column(Integer)
    traffic_gb: Mapped[int] = mapped_column(Integer)  # 0 = unlimited
    max_devices: Mapped[int | None] = mapped_column(Integer)
    specs: Mapped[dict | None] = mapped_column(JSON)
    main_price: Mapped[int] = mapped_column(BigInteger)
    reseller_price: Mapped[int] = mapped_column(BigInteger)  # V1: same for all resellers
    currency: Mapped[str] = mapped_column(String(8), default="IRT")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    default_panel_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("panel_groups.id", ondelete="SET NULL"), index=True, nullable=True)


class StoreProduct(IdMixin, TimestampMixin, Base):
    """Admin controls availability per store; reseller sets customer_price for allowed products."""

    __tablename__ = "store_products"
    __table_args__ = (UniqueConstraint("store_id", "product_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id"), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # set by admin
    customer_price: Mapped[int | None] = mapped_column(BigInteger)  # set by reseller
    is_listed: Mapped[bool] = mapped_column(Boolean, default=True)  # reseller can hide


class StorePoolPrice(IdMixin, TimestampMixin, Base):
    """A reseller's retail price for ONE package inside ONE sales bundle of their own store.

    It overrides ``StoreProduct.customer_price`` (the store-wide price of the package) for that pool only, so a
    reseller can sell the same package at a different price in a direct pool and in a tunnel pool. The row exists
    only while a price is set: clearing the price deletes the row and the pool falls back to the store-wide price.
    The price is never below the pool's reseller price (the reseller's cost); the core enforces that.
    """

    __tablename__ = "store_pool_prices"
    __table_args__ = (UniqueConstraint("store_id", "panel_group_id", "product_id"),)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    panel_group_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panel_groups.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id", ondelete="CASCADE"), index=True)
    customer_price: Mapped[int] = mapped_column(BigInteger)


class Coupon(IdMixin, TimestampMixin, Base):
    """V1.1 coupon. Validation, scope, quota and selection happen only in Core (domain/coupon.py)."""

    __tablename__ = "coupons"
    __table_args__ = (UniqueConstraint("owner_key", "code"),)
    code: Mapped[str] = mapped_column(String(50), index=True)
    owner_key: Mapped[str] = mapped_column(String(64))  # store id (scope=store) or "admin" (scope=domain)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    scope: Mapped[str] = mapped_column(String(10), default="store")  # store | domain
    allowed_store_ids: Mapped[list | None] = mapped_column(JSON)  # domain scope (Admin only)
    allowed_store_kinds: Mapped[list | None] = mapped_column(JSON)  # domain scope, e.g. ["reseller"]
    product_ids: Mapped[list | None] = mapped_column(JSON)
    creator_type: Mapped[str] = mapped_column(String(10), default="admin")  # admin | reseller
    creator_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    funded_by: Mapped[str] = mapped_column(String(10), default="store")  # store | platform (reseller cost reduced)
    percent_bp: Mapped[int] = mapped_column(Integer, default=0)
    fixed: Mapped[int] = mapped_column(BigInteger, default=0)
    max_discount: Mapped[int | None] = mapped_column(BigInteger)
    min_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str | None] = mapped_column(String(8))
    starts_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    per_customer_limit: Mapped[int | None] = mapped_column(Integer, default=1)
    redemptions: Mapped[int] = mapped_column(Integer, default=0)
    combinable: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | disabled | archived


class CouponRedemption(IdMixin, CreatedMixin, Base):
    __tablename__ = "coupon_redemptions"
    __table_args__ = (UniqueConstraint("coupon_id", "order_id"),)
    coupon_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("coupons.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20), default="applied")  # applied | reversed
