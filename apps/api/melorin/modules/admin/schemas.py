import datetime as dt
import uuid

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class CreateProduct(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    category: str | None = None
    duration_days: int = Field(gt=0)
    traffic_gb: int = Field(ge=0)
    max_devices: int | None = Field(default=None, gt=0)
    main_price: int = Field(ge=0)
    reseller_price: int = Field(ge=0)
    currency: Literal["IRT", "USD", "USDT", "XTR"] = "IRT"
    is_test: bool = False
    default_panel_group_id: uuid.UUID | None = None


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
    default_panel_group_id: uuid.UUID | None = None


class ProductOut(CreateProduct):
    id: uuid.UUID
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class Availability(BaseModel):
    store_id: uuid.UUID
    enabled: bool = True
    customer_price: int | None = Field(default=None, ge=0)
    listed: bool = True


class CreatePanel(BaseModel):
    name: str
    kind: str = Field(pattern="^(sanaei|pasarguard|mock)$")
    base_url: str
    credentials: dict = {}
    config: dict = {}

    @model_validator(mode="after")
    def _sanaei_contract(self):
        # 3x-ui needs a subscription base (served on a separate Sub Port/Path) and a target inbound,
        # otherwise provisioning creates panel clients that can never be delivered.
        if self.kind == "sanaei":
            cfg, cred = self.config or {}, self.credentials or {}
            if cred and not (cred.get("api_token") or (cred.get("username") and cred.get("password"))):
                raise ValueError("sanaei: credentials need api_token or username+password")
            if not str(cfg.get("sub_base_url") or "").startswith(("http://", "https://")):
                raise ValueError("sanaei: config.sub_base_url is required, e.g. https://sub.example.com:2096/sub")
            if not (cfg.get("inbound_ids") or cfg.get("inbound_id") or cfg.get("template_username")):
                raise ValueError("sanaei: config.inbound_ids or config.template_username is required")
            if cfg.get("api_style", "auto") not in ("auto", "v3", "legacy"):
                raise ValueError("sanaei: config.api_style must be auto, v3 or legacy")
        if self.kind == "pasarguard":
            cfg, cred = self.config or {}, self.credentials or {}
            if cred and not (cred.get("api_key") or cred.get("access_token") or (cred.get("username") and cred.get("password"))):
                raise ValueError("pasarguard: credentials need api_key, access_token or username+password")
            template_id = cfg.get("user_template_id")
            if template_id is None and not cfg.get("group_ids"):
                raise ValueError("pasarguard: config.group_ids or config.user_template_id is required")
            if template_id is not None:
                try:
                    if int(template_id) <= 0:
                        raise ValueError
                except (TypeError, ValueError) as exc:
                    raise ValueError("pasarguard: config.user_template_id must be a positive integer") from exc
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
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class PanelState(BaseModel):
    is_enabled: bool


class CreatePanelGroup(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    selection_mode: str = Field(default="automatic", pattern="^(automatic|manual)$")
    naming_mode: str = Field(default="automatic", pattern="^(automatic|custom)$")
    kind_label: str = Field(default="", max_length=40)
    is_enabled: bool = True
    reseller_enabled: bool = True
    sales_limit: int | None = Field(default=None, gt=0)
    panel_ids: list[uuid.UUID] = Field(default_factory=list)
    member_labels: dict[uuid.UUID, str] = Field(default_factory=dict)  # panel_id -> what the customer sees (manual bundles)


class UpdatePanelGroup(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    selection_mode: str | None = Field(default=None, pattern="^(automatic|manual)$")
    naming_mode: str | None = Field(default=None, pattern="^(automatic|custom)$")
    kind_label: str | None = Field(default=None, max_length=40)
    is_enabled: bool | None = None
    reseller_enabled: bool | None = None
    sales_limit: int | None = Field(default=None, gt=0)
    panel_ids: list[uuid.UUID] | None = None
    member_labels: dict[uuid.UUID, str] | None = None


class PanelGroupMemberInput(BaseModel):
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


class UpdateServer(BaseModel):
    """Partial update: only the fields present in the request body are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    panel_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=100)
    capacity: int | None = Field(default=None, gt=0, le=100000)
    product_codes: list[str] | None = None
    allow_test: bool | None = None


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
