"""Architecture guard: account placement belongs to the core, not to a channel."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_migration_0013_follows_0012_and_matches_the_model():
    src = read("apps/api/alembic/versions/0013_product_default_panel_group.py")
    assert 'down_revision = "0012_baskets_to_panel_groups"' in src
    assert "default_panel_group_id" in src and 'ondelete="SET NULL"' in src


def test_channels_never_choose_a_server():
    # Channels say WHAT is bought and, since sales bundles, which pool the customer picked (and the panel in a
    # manual pool). The core validates every choice; the server is never chosen outside the core.
    for rel in ("apps/telegram-main/runner.py", "apps/store-web/src/App.jsx"):
        src = read(rel)
        for forbidden in ("server_id", "default_panel_group"):
            assert forbidden not in src, f"{rel} must not carry allocation data ({forbidden})"
        assert "/orders" in src


def test_every_choice_a_channel_sends_is_validated_by_the_core_before_payment():
    create = _called_names(_function("apps/api/melorin/modules/orders/service.py", "create_order"))
    assert create.index("plan_sale") < create.index("pay_with_wallet")
    plan = _called_names(_function("apps/api/melorin/modules/vpn/allocation.py", "plan_sale"))
    assert plan.index("resolve_order_group") < plan.index("requested_account_name") < plan.index("pool_product")


def test_bot_and_site_share_one_core_order_endpoint():
    router = read("apps/api/melorin/modules/orders/router.py")
    assert "service.create_order(" in router


def _called_names(func: ast.AsyncFunctionDef) -> list[str]:
    calls = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            calls.append((node.lineno, node.col_offset, f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")))
    return [name for _, _, name in sorted(calls)]  # source order


def _function(rel, name):
    tree = ast.parse(read(rel))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def test_purchase_and_test_orders_use_core_group_rule_before_any_payment():
    create = _called_names(_function("apps/api/melorin/modules/orders/service.py", "create_order"))
    assert "plan_sale" in create
    assert create.index("plan_sale") < create.index("pay_with_wallet")
    assert "resolve_order_group" in _called_names(_function("apps/api/melorin/modules/orders/service.py", "create_test_order"))


def test_provisioning_places_accounts_only_through_the_core():
    svc = read("apps/api/melorin/modules/vpn/service.py")
    assert "resolve_allocation(" in svc
    assert "def choose_server" not in svc and "def choose_panel_group_panel" not in svc
    assert "select(Server" not in svc


def test_server_product_codes_must_exist():
    src = read("apps/api/melorin/modules/admin/router.py")
    assert "UNKNOWN_PRODUCT_CODES" in src
