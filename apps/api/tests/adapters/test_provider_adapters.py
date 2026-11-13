"""T16/T65: the three panel families (sanaei, pasarguard, upstream_bot) stay, but only as plug-in adapters.

* every family is declared once (providers.PROVIDERS) and resolved lazily;
* settings/target rules live in the family's own ``contract`` module and behave exactly as before;
* nothing outside the adapter layer imports a concrete family (guard), and upstream_bot works without Telethon installed.
"""

import ast
import pathlib
import re
import subprocess
import sys

import pytest
from pydantic import ValidationError

from melorin.modules.admin.schemas import CreatePanel
from melorin.modules.panel_integrations import targets
from melorin.modules.panel_integrations.adapters import providers, registry

ROOT = pathlib.Path(__file__).resolve().parents[2] / "melorin"
FAMILIES = {"sanaei", "pasarguard", "upstream_bot"}
_CONTRACT_METHODS = (
    "health_check",
    "capabilities",
    "create_account",
    "get_account",
    "suspend_account",
    "resume_account",
    "extend_account",
    "revoke_account",
    "close",
    "normalize_status",
)


def test_all_three_families_and_mock_are_declared():
    assert FAMILIES | {"mock"} == set(providers.kinds())
    assert FAMILIES | {"mock"} == set(registry.ADAPTERS)


@pytest.mark.parametrize("kind", sorted(FAMILIES | {"mock"}))
def test_each_spec_resolves_to_a_panel_adapter(kind):
    cls = registry.ADAPTERS[kind]
    missing = [m for m in _CONTRACT_METHODS if not callable(getattr(cls, m, None))]
    assert not missing, f"{kind} adapter lacks {missing}"
    assert providers.spec_for(kind).label


def test_unknown_kind_is_a_keyerror_and_strict_by_default():
    with pytest.raises(KeyError):
        registry.ADAPTERS["nope"]
    assert providers.enforces_egress_policy("nope") is True
    assert providers.supports("nope", "panel_ops") is False
    assert providers.target_kinds("nope") == ()


def test_features_and_transport_are_declared_not_hardcoded():
    assert providers.supports("pasarguard", "panel_ops") and providers.supports("pasarguard", "webhook_events")
    assert not providers.supports("sanaei", "panel_ops") and not providers.supports("upstream_bot", "panel_ops")
    assert providers.enforces_egress_policy("sanaei") and providers.enforces_egress_policy("pasarguard")
    assert providers.enforces_egress_policy("upstream_bot") is False  # Telegram transport, not an HTTP panel URL
    assert providers.target_kinds("pasarguard") == ("group", "template") and providers.target_kinds("sanaei") == ("inbound",)


def test_unknown_feature_in_a_spec_is_rejected():
    with pytest.raises(ValueError):
        providers.ProviderSpec(kind="x", label="x", adapter="a:B", transport="https", features=frozenset({"magic"}))


def test_register_override_and_new_family(monkeypatch):
    class Fake:  # pragma: no cover - only referenced by name
        pass

    monkeypatch.setattr(providers, "PROVIDERS", dict(providers.PROVIDERS))
    monkeypatch.setattr(registry.ADAPTERS, "_override", {})
    registry.register("marzban", Fake)
    assert registry.ADAPTERS["marzban"] is Fake
    assert providers.spec_for("marzban").transport == "https" and providers.enforces_egress_policy("marzban")
    assert "marzban" in registry.ADAPTERS


def _panel(kind, credentials=None, config=None):
    return CreatePanel(name="p", kind=kind, base_url="https://p.example.com", credentials=credentials or {}, config=config or {})


@pytest.mark.parametrize(
    ("kind", "credentials", "config", "message"),
    [
        ("sanaei", {"api_token": "t"}, {"inbound_ids": [1]}, "sub_base_url is required"),
        ("sanaei", {"x": 1}, {"sub_base_url": "https://s", "inbound_ids": [1]}, "need api_token or username+password"),
        ("sanaei", {}, {"sub_base_url": "https://s"}, "inbound_ids or config.template_username"),
        ("sanaei", {}, {"sub_base_url": "https://s", "inbound_ids": [1], "api_style": "x"}, "api_style must be"),
        ("pasarguard", {"x": 1}, {"group_ids": [1]}, "need api_key, access_token or username+password"),
        ("pasarguard", {}, {}, "group_ids or config.user_template_id is required"),
        ("pasarguard", {}, {"user_template_id": 0}, "positive integer"),
        ("upstream_bot", {"api_id": 1}, {"max_price": 5}, "need api_id, api_hash and session"),
        ("upstream_bot", {}, {}, "max_price (toman, safety cap per purchase) is required"),
        ("upstream_bot", {}, {"max_price": 5, "plans": [{"traffic_gb": 0}]}, "traffic_gb > 0"),
        ("upstream_bot", {}, {"max_price": 5, "renew": []}, "renew must be an object"),
        ("upstream_bot", {}, {"max_price": 5, "poll_interval": -1}, "poll_interval must be a positive number"),
    ],
)
def test_family_contract_rejects_with_its_own_message(kind, credentials, config, message):
    with pytest.raises(ValidationError, match=re.escape(message)):
        _panel(kind, credentials, config)


@pytest.mark.parametrize(
    ("kind", "credentials", "config"),
    [
        ("sanaei", {"api_token": "t"}, {"sub_base_url": "https://s/sub", "inbound_ids": [1]}),
        ("pasarguard", {"api_key": "k"}, {"group_ids": [1]}),
        ("pasarguard", {}, {"user_template_id": 3}),
        ("upstream_bot", {"api_id": 1, "api_hash": "h", "session": "s"}, {"max_price": 100000, "plans": [{"traffic_gb": 10, "months": 1}]}),
        ("mock", {}, {}),
    ],
)
def test_family_contract_accepts_valid_settings(kind, credentials, config):
    assert _panel(kind, credentials, config).kind == kind


@pytest.mark.parametrize(
    ("kind", "target", "api_style", "expected"),
    [
        ("pasarguard", {"group_ids": [1, 2]}, None, []),
        (
            "pasarguard",
            {"group_ids": [1], "user_template_id": 2},
            None,
            ["برای پاسارگارد دقیقاً یکی از گروه‌ها (group_ids) یا تمپلیت (user_template_id) لازم است."],
        ),
        ("pasarguard", {"user_template_id": 2, "limits_from": "x"}, None, ["limits_from باید product یا template باشد."]),
        ("sanaei", {"inbound_ids": [4, 5]}, "v3", []),
        ("sanaei", {"inbound_ids": [4, 5]}, "legacy", ["سنایی نسخه‌ی قدیمی (legacy) فقط یک اینباند را پشتیبانی می‌کند."]),
        ("sanaei", {"group_ids": [1]}, None, ["کلید نامعتبر برای سنایی: group_ids", "inbound_ids باید فهرست غیرتهی از عددهای مثبت باشد."]),
        ("upstream_bot", {"group_ids": [1]}, None, ["پنل از نوع upstream_bot مقصد جداگانه پشتیبانی نمی‌کند."]),
        ("mock", {"x": 1}, None, ["پنل از نوع mock مقصد جداگانه پشتیبانی نمی‌کند."]),
    ],
)
def test_target_validation_delegates_to_the_family(kind, target, api_style, expected):
    assert targets.validate_target(kind, target, api_style=api_style) == expected
    assert targets.validate_target(kind, None) == [] and targets.validate_target(kind, "x") == ["مقصد باید یک شیء باشد."]


def test_capacity_label_per_family():
    assert targets.capacity_label("pasarguard", {"group_ids": [1]}) == "ظرفیت گروه"
    assert targets.capacity_label("pasarguard", {"user_template_id": 1}) == "ظرفیت تمپلیت"
    assert targets.capacity_label("sanaei", {"inbound_ids": [1]}) == "ظرفیت اینباند"
    assert targets.capacity_label("pasarguard", None) == "ظرفیت مقصد"
    assert targets.capacity_label("upstream_bot", {"x": 1}) == "ظرفیت مقصد"


def test_listing_warnings_come_from_the_family():
    listing = {"groups": [{"id": 1, "disabled": True}], "templates": [], "inbounds": [{"id": 4, "enabled": False}]}
    assert providers.target_warnings("pasarguard", {"group_ids": [1, 9]}, listing) == [
        "گروه 1 روی پنل غیرفعال است.",
        "گروه 9 روی پنل پیدا نشد.",
    ]
    assert providers.target_warnings("sanaei", {"inbound_ids": [4, 7]}, listing) == [
        "اینباند 4 روی پنل غیرفعال است.",
        "اینباند 7 روی پنل پیدا نشد.",
    ]
    assert providers.target_warnings("upstream_bot", {"x": 1}, listing) == []


# --- boundaries ------------------------------------------------------------------------------------------------------------------

_FAMILY_PKGS = (
    "melorin.modules.panel_integrations.adapters.sanaei",
    "melorin.modules.panel_integrations.adapters.pasarguard",
    "melorin.modules.panel_integrations.adapters.upstream_bot",
)
# The only places allowed to name a concrete family: the adapter layer itself, plus the two PasarGuard wire-format parsers that
# the webhook/event consumers must read (a PasarGuard-only feature, gated by providers.supports(..., "webhook_events")).
_ALLOWED = {
    "melorin/modules/panel_integrations/adapters/providers.py",
    "melorin/modules/vpn/webhook_router.py",
    "melorin/modules/vpn/panel_events.py",
    "melorin/modules/panelops/service_access.py",
    "melorin/modules/panelops/settings_drift.py",
}


def _imports(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def test_only_the_adapter_layer_imports_a_concrete_family():
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT.parent).as_posix()
        if rel.startswith(
            (
                "melorin/modules/panel_integrations/adapters/sanaei/",
                "melorin/modules/panel_integrations/adapters/pasarguard/",
                "melorin/modules/panel_integrations/adapters/upstream_bot/",
            )
        ):
            continue
        if rel in _ALLOWED:
            continue
        if any(m == pkg or m.startswith(pkg + ".") for m in _imports(path) for pkg in _FAMILY_PKGS):
            offenders.append(rel)
    assert not offenders, f"concrete provider imported outside the adapter layer (use providers/registry): {offenders}"


def test_registry_import_does_not_pull_in_any_family():
    code = (
        "import sys\n"
        "import melorin.modules.panel_integrations.adapters.registry\n"
        "bad = [m for m in sys.modules if m.startswith('melorin.modules.panel_integrations.adapters.') and m.split('.')[4] in ('sanaei','pasarguard','upstream_bot')]\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT.parent, check=True).stdout.strip()
    assert out == "", f"families were imported eagerly: {out}"


def test_upstream_bot_loads_without_telethon():
    code = (
        "import sys\nsys.modules['telethon'] = None\n"  # makes `import telethon` raise ImportError
        "from melorin.modules.panel_integrations.adapters import registry\n"
        "cls = registry.ADAPTERS['upstream_bot']\nprint(cls.__name__)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT.parent, check=True).stdout.strip()
    assert out == "UpstreamBotAdapter"
