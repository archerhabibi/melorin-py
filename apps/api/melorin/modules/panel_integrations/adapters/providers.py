"""Panel providers as plug-in adapters (audit T16, T65).

Melorin keeps THREE provider families - ``sanaei`` (3x-ui), ``pasarguard`` and ``upstream_bot`` (a reseller bot driven through a user
account) - plus ``mock`` for tests. The rest of the code must not know which family it talks to. This module is the one place that
says what each family is:

* a :class:`ProviderSpec` describes it declaratively (label, transport, features, the dotted path of its adapter class, and the
  dotted path of its ``contract`` module that validates settings/targets);
* the adapter class and the contract are imported LAZILY, on first use, so a family that is not configured (or whose optional
  dependency, e.g. Telethon for ``upstream_bot``, is absent) never costs an import or a failure at start-up;
* callers ask questions (``supports(kind, "panel_ops")``, ``target_kinds(kind)``, ``validate_settings(...)``) instead of comparing
  ``panel.kind`` with a string.

A new family (Marzban, Hiddify, ...) is one ``register_provider(ProviderSpec(...))`` call; nothing else changes.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Literal

Transport = Literal["https", "telegram", "in_process"]

# Features a family may declare. ``panel_ops`` = groups/templates/events/admins/capacity/bulk tooling (the PasarGuard feature set).
FEATURES = frozenset({"panel_ops", "webhook_events", "per_store_admin", "name_mapping"})


@dataclass(frozen=True)
class ProviderSpec:
    kind: str
    label: str
    adapter: str  # "package.module:ClassName"
    transport: Transport
    contract: str | None = None  # "package.module" exposing validate_settings / validate_target / capacity_label (all optional)
    features: frozenset[str] = frozenset()
    target_kinds: tuple[str, ...] = ()  # kinds of destination a server slot may name ("group", "template", "inbound")
    egress_policy: bool = True  # panel_url must be public https (staging/production). False for non-HTTP transports.
    optional_dependency: str | None = None  # import name that is needed at run time only (informational; failures stay PanelError)
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        unknown = set(self.features) - FEATURES
        if unknown:
            raise ValueError(f"provider {self.kind}: unknown features {sorted(unknown)}")


def _load(path: str, attr: str | None = None):
    module_name, _, name = path.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr or name) if (attr or name) else module


_BASE = "melorin.modules.panel_integrations.adapters"

PROVIDERS: dict[str, ProviderSpec] = {}


def register_provider(spec: ProviderSpec) -> ProviderSpec:
    PROVIDERS[spec.kind] = spec
    return spec


register_provider(
    ProviderSpec(
        kind="sanaei",
        label="3x-ui (Sanaei)",
        adapter=f"{_BASE}.sanaei:SanaeiAdapter",
        contract=f"{_BASE}.sanaei.contract",
        transport="https",
        target_kinds=("inbound",),
    )
)
register_provider(
    ProviderSpec(
        kind="pasarguard",
        label="PasarGuard",
        adapter=f"{_BASE}.pasarguard:PasarGuardAdapter",
        contract=f"{_BASE}.pasarguard.contract",
        transport="https",
        features=frozenset({"panel_ops", "webhook_events", "per_store_admin"}),
        target_kinds=("group", "template"),
    )
)
register_provider(
    ProviderSpec(
        kind="upstream_bot",
        label="Upstream reseller bot (Telethon)",
        adapter=f"{_BASE}.upstream_bot:UpstreamBotAdapter",
        contract=f"{_BASE}.upstream_bot.contract",
        transport="telegram",
        features=frozenset({"name_mapping"}),
        egress_policy=False,
        optional_dependency="telethon",
    )
)
register_provider(ProviderSpec(kind="mock", label="Mock (tests)", adapter=f"{_BASE}.mock:MockPanelAdapter", transport="in_process"))


class AdapterClasses(MutableMapping):
    """``registry.ADAPTERS``: kind -> adapter class, resolved lazily from :data:`PROVIDERS`. Assigning a class (``register``)
    overrides the lazy one, which keeps ``register()`` and the tests' ``monkeypatch.setitem`` working."""

    def __init__(self) -> None:
        self._override: dict[str, type] = {}

    def __getitem__(self, kind: str) -> type:
        if kind in self._override:
            return self._override[kind]
        spec = PROVIDERS.get(kind)
        if spec is None:
            raise KeyError(kind)
        return _load(spec.adapter)

    def __setitem__(self, kind: str, cls: type) -> None:
        self._override[kind] = cls

    def __delitem__(self, kind: str) -> None:
        if kind in self._override:
            del self._override[kind]
        else:
            raise KeyError(kind)

    def __iter__(self) -> Iterator[str]:
        return iter(dict.fromkeys([*PROVIDERS, *self._override]))

    def __len__(self) -> int:
        return len(set(PROVIDERS) | set(self._override))

    def __contains__(self, kind: object) -> bool:
        return kind in PROVIDERS or kind in self._override


def spec_for(kind: str) -> ProviderSpec | None:
    return PROVIDERS.get(kind)


def kinds() -> list[str]:
    return sorted(PROVIDERS)


def supports(kind: str, feature: str) -> bool:
    spec = PROVIDERS.get(kind)
    return bool(spec and feature in spec.features)


def target_kinds(kind: str) -> tuple[str, ...]:
    spec = PROVIDERS.get(kind)
    return spec.target_kinds if spec else ()


def enforces_egress_policy(kind: str) -> bool:
    """True when the panel URL must be public https in staging/production. Unknown kinds keep the strict default."""
    spec = PROVIDERS.get(kind)
    return True if spec is None else spec.egress_policy


def contract_of(kind: str):
    """The family's contract module, or None when it has none (mock) or is unknown."""
    spec = PROVIDERS.get(kind)
    if spec is None or not spec.contract:
        return None
    return _load(spec.contract, attr="")


def validate_settings(kind: str, credentials: dict | None, config: dict | None) -> None:
    """Raise ``ValueError`` (the family's own message) when credentials/config cannot work for this family. No-op without a contract."""
    contract = contract_of(kind)
    check = getattr(contract, "validate_settings", None)
    if callable(check):
        check(credentials or {}, config or {})


def validate_target(kind: str, target: dict, *, api_style: str | None = None) -> list[str]:
    contract = contract_of(kind)
    check = getattr(contract, "validate_target", None)
    if callable(check):
        return check(target, api_style=api_style)
    return [f"پنل از نوع {kind} مقصد جداگانه پشتیبانی نمی‌کند."]


def capacity_label(kind: str, target: dict | None) -> str:
    contract = contract_of(kind)
    label = getattr(contract, "capacity_label", None)
    return label(target) if callable(label) and target else "ظرفیت مقصد"


def target_warnings(kind: str, target: dict, listing: dict) -> list[str]:
    contract = contract_of(kind)
    check = getattr(contract, "listing_warnings", None)
    return check(target, listing) if callable(check) else []
