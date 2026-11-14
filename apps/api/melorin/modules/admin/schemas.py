import datetime as dt
import uuid

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CreateProduct(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    category: str | None = None
    duration_days: int = Field(gt=0)
    traffic_gb: int = Field(ge=0)
    max_devices: int | None = Field(default=None, gt=0)
    main_price: int = Field(ge=0)
    # The cooperation (reseller) price is set per sales bundle; this is only the fallback. Omitted = same as main_price.
    reseller_price: int | None = Field(default=None, ge=0)
    currency: Literal["IRT", "USD", "USDT", "XTR"] = "IRT"
    is_test: bool = False
    reseller_enabled: bool = True
    default_bundle_id: uuid.UUID | None = None  # only used by test packages; normal packages are sold in every bundle


class ProductPatch(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=50, pattern="^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    category: str | None = None
    duration_days: int | None = Field(default=None, gt=0)
    traffic_gb: int | None = Field(default=None, ge=0)
    max_devices: int | None = Field(default=None, gt=0)
    main_price: int | None = Field(default=None, ge=0)
    reseller_price: int | None = Field(default=None, ge=0)
    currency: Literal["IRT", "USD", "USDT", "XTR"] | None = None
    is_test: bool | None = None
    is_active: bool | None = None
    reseller_enabled: bool | None = None
    default_bundle_id: uuid.UUID | None = None


class ProductOut(CreateProduct):
    id: uuid.UUID
    is_active: bool
    reseller_price: int
    created_at: dt.datetime
    updated_at: dt.datetime


class Availability(BaseModel):
    store_id: uuid.UUID
    enabled: bool = True
    customer_price: int | None = Field(default=None, ge=0)
    listed: bool = True


class CreatePanel(BaseModel):
    name: str
    kind: str = Field(pattern="^(sanaei|pasarguard|upstream_bot|mock)$")
    base_url: str
    credentials: dict = {}
    config: dict = {}

    @model_validator(mode="after")
    def _provider_contract(self):
        # Each provider family validates its own credentials/config (adapters/<kind>/contract.py); this model never branches on kind.
        from melorin.modules.panel_integrations.adapters import providers

        providers.validate_settings(self.kind, self.credentials, self.config)
        return self


class CreateBotStoreBinding(BaseModel):
    bot_key: str = Field(min_length=8, max_length=120)
    bot_username: str | None = Field(default=None, max_length=100)
    store_id: uuid.UUID
    bot_kind: str = Field(default="reseller", pattern="^(main|reseller)$")
    config: dict = Field(default_factory=dict)


class PanelOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    base_url: str
    is_enabled: bool
    health_status: str
    last_health_at: dt.datetime | None
    last_health_error: str | None = None
    config: dict | None = None
    has_credentials: bool = False
    # PG-00: effective capability flags + why a supported feature is denied (see modules/panel_integrations/capabilities.py); the UI hides what is off
    capabilities: dict | None = None
    # PG-01: node-level health (counts, failing nodes with fix hints, ``sellable``); ``health_status`` may be ``degraded``
    health_detail: dict | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class PanelState(BaseModel):
    is_enabled: bool


class CreateBundle(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    selection_mode: str = Field(default="automatic", pattern="^(automatic|manual)$")
    balancing: str = Field(default="round_robin", pattern="^(round_robin|least_fill|fill_first)$")
    naming_mode: str = Field(default="automatic", pattern="^(automatic|custom)$")
    kind_label: str = Field(default="", max_length=40)
    is_enabled: bool = True
    reseller_enabled: bool = True
    sales_limit: int | None = Field(default=None, gt=0)
    panel_ids: list[uuid.UUID] = Field(default_factory=list)
    member_labels: dict[uuid.UUID, str] = Field(default_factory=dict)  # panel_id -> what the customer sees (manual bundles)


class UpdateBundle(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    selection_mode: str | None = Field(default=None, pattern="^(automatic|manual)$")
    balancing: str | None = Field(default=None, pattern="^(round_robin|least_fill|fill_first)$")
    naming_mode: str | None = Field(default=None, pattern="^(automatic|custom)$")
    kind_label: str | None = Field(default=None, max_length=40)
    is_enabled: bool | None = None
    reseller_enabled: bool | None = None
    sales_limit: int | None = Field(default=None, gt=0)
    panel_ids: list[uuid.UUID] | None = None
    member_labels: dict[uuid.UUID, str] | None = None


class BundleMemberInput(BaseModel):
    panel_id: uuid.UUID
    is_enabled: bool = True
    sales_limit: int | None = Field(default=None, gt=0)
    sort: int = 0


class CreateServer(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    panel_id: uuid.UUID
    location: str | None = Field(default=None, max_length=100)
    capacity: int = Field(gt=0, le=100000)
    product_codes: list[str] | None = None
    allow_test: bool = True
    target: dict | None = None  # destination on the panel (group/template/inbound set); null = inherit the panel config


class UpdateServer(BaseModel):
    """Partial update: only the fields present in the request body are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    panel_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=100)
    capacity: int | None = Field(default=None, gt=0, le=100000)
    product_codes: list[str] | None = None
    allow_test: bool | None = None
    target: dict | None = None  # explicit null clears the target (= inherit panel.config)
    capacity_source: str | None = Field(default=None, pattern="^(melorin|panel)$")  # PG-08: whose count fills the destination


class ServerOut(BaseModel):
    id: uuid.UUID
    name: str
    panel_id: uuid.UUID
    panel_name: str
    location: str | None = None
    capacity: int
    product_codes: list[str] | None = None
    allow_test: bool
    is_enabled: bool
    active_accounts: int = 0
    total_accounts: int = 0
    target: dict | None = None
    effective_target: dict = Field(default_factory=dict)  # what new accounts really use (target laid over the panel config)
    capacity_label: str = "ظرفیت مقصد"  # گروه / تمپلیت / اینباند / مقصد (D7)
    last_assigned_at: dt.datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    # PG-08: the destination's real state on the panel and its fill level (Melorin's count beside the panel's own)
    sellable: bool = True
    sellable_reason: str | None = None
    destination_health: dict | None = None
    capacity_info: dict = Field(default_factory=dict)
    capacity_source: str = "panel"
    capacity_checked_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class FeatureUpdate(BaseModel):
    enabled: bool
    scope_type: str = "global"
    scope_id: str = "*"
    note: str | None = None


class SettingUpdate(BaseModel):
    value: object


class ReviewPayment(BaseModel):
    approve: bool
    reason: str | None = None


class ResellerApproval(BaseModel):
    approve: bool
    debt_limit: int = Field(default=0, ge=0)
    reason: str | None = None


class OrderAction(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class AttachExistingAccount(BaseModel):
    server_id: uuid.UUID
    username: str
    panel_ref: str | None = None
    subscription_url: str | None = None
    reason: str | None = None


class BundleProductIn(BaseModel):
    """A package inside a bundle. A null price means "use the product's own price"."""

    main_price: int | None = Field(default=None, ge=0)
    reseller_price: int | None = Field(default=None, ge=0)
    is_listed: bool = True
    sort: int = 0
