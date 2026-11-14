"""Pure rules of the admin team: the permission matrix, the path -> area table and the password policy (docs/24-Admin-Team-Design.md)."""

import pytest

from melorin.domain import admin_access as aa
from melorin.domain import password_policy as pp


# ---------------------------------------------------------------- path -> area
@pytest.mark.parametrize(
    "path, method, area, write",
    [
        ("/api/v1/admin/orders", "GET", "orders", False),
        ("/api/v1/admin/orders/123/refund", "POST", "orders", True),
        ("/api/v1/admin/payments/1/review", "POST", "payments", True),
        ("/api/v1/admin/stores/abc/bank-sms", "GET", "payments", False),
        ("/api/v1/admin/stores/abc/receipt-review/9", "POST", "payments", True),
        ("/api/v1/admin/stores/abc/vpn-notices", "PUT", "infrastructure", True),
        ("/api/v1/admin/stores/abc/referrals/summary", "GET", "catalog", False),
        ("/api/v1/admin/stores", "GET", "resellers", False),
        ("/api/v1/admin/panels/1/state", "POST", "infrastructure", True),
        ("/api/v1/admin/products", "POST", "catalog", True),
        ("/api/v1/admin/coupons/1", "PATCH", "catalog", True),
        ("/api/v1/admin/resellers/1/bot-token", "PUT", "resellers", True),
        ("/api/v1/admin/users", "GET", "customers", False),
        ("/api/v1/admin/vpn-accounts/1/tools/devices/reset", "POST", "customers", True),
        ("/api/v1/admin/tickets/1", "PATCH", "support", True),
        ("/api/v1/admin/audit", "GET", "audit", False),
        ("/api/v1/admin/dashboard", "GET", "overview", False),
        ("/api/v1/admin/reports/summary", "GET", "reports", False),
        ("/api/v1/reports/payments", "GET", "reports", False),
        ("/api/v1/admin/settings/x", "PUT", "system", True),
        ("/api/v1/admin/integrations/google", "PUT", "system", True),
        ("/api/v1/admin/feature-flags/x", "PUT", "system", True),
        ("/api/v1/admin/telegram/button-styles", "GET", "system", False),
        ("/api/v1/admin/telegram/button-styles", "PUT", "system", True),
        ("/api/v1/admin/telegram/button-styles/preview", "POST", "system", True),
        ("/api/v1/admin/admins", "GET", "admins", False),
        ("/api/v1/admin/admins/1/reset-access", "POST", "admins", True),
        ("/api/v1/admin/me", "GET", "self", False),
        ("/api/v1/auth/admin/password", "POST", "self", True),
    ],
)
def test_path_rules(path, method, area, write):
    assert aa.area_for(path, method) == (area, write)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/panel-admins/1/credentials",
        "/api/v1/admin/panels/1/service-access",
        "/api/v1/admin/stores/1/bank-sms/token",
    ],
)
def test_secret_revealing_gets_need_write_access(path):
    _, write = aa.area_for(path, "GET")
    assert write is True


def test_unknown_admin_path_falls_into_the_owner_only_area():
    assert aa.area_for("/api/v1/admin/brand-new-thing", "GET") == ("system", False)
    assert aa.allows([aa.MANAGER], "system") is False
    assert aa.allows([aa.OWNER], "system", write=True) is True


def test_query_string_and_trailing_slash_do_not_change_the_area():
    assert aa.area_for("/api/v1/admin/orders/?q=1", "GET") == ("orders", False)


def test_a_prefix_lookalike_is_not_mistaken_for_an_area():
    # "orders-export" must not inherit the orders grant; it is unknown, therefore owner-only
    assert aa.area_for("/api/v1/admin/orders-export", "GET")[0] == "system"
    assert aa.area_for("/api/v1/admin/administrators", "GET")[0] == "system"


# ---------------------------------------------------------------- the matrix
def test_every_role_is_defined_and_only_over_known_areas():
    assert set(aa.GRANTS) == set(aa.ROLES)
    for grants in aa.GRANTS.values():
        assert set(grants) <= set(aa.AREAS)
        assert set(grants.values()) <= {aa.READ, aa.WRITE}


def test_every_path_rule_points_at_a_known_area():
    assert {area for _, area, _ in aa.PATH_RULES} <= set(aa.AREAS)


def test_only_the_owner_manages_the_team_and_the_system():
    for role in aa.ROLES:
        owner = role == aa.OWNER
        assert aa.allows([role], "admins") is owner
        assert aa.allows([role], "system") is owner


def test_owner_has_everything():
    assert all(aa.allows([aa.OWNER], area, write=True) for area in aa.AREAS)


def test_viewer_can_read_operations_but_never_write():
    for area in ("overview", "reports", "orders", "payments", "catalog", "infrastructure", "resellers", "customers", "support"):
        assert aa.allows([aa.VIEWER], area) and not aa.allows([aa.VIEWER], area, write=True)
    assert aa.allows([aa.VIEWER], "audit") is False


def test_finance_pays_and_support_supports():
    assert aa.allows([aa.FINANCE], "payments", write=True) and aa.allows([aa.FINANCE], "orders", write=True)
    assert not aa.allows([aa.FINANCE], "infrastructure") and not aa.allows([aa.FINANCE], "support")
    assert aa.allows([aa.SUPPORT], "support", write=True) and aa.allows([aa.SUPPORT], "customers", write=True)
    assert not aa.allows([aa.SUPPORT], "payments", write=True) and not aa.allows([aa.SUPPORT], "infrastructure")


def test_manager_runs_operations_but_audit_is_read_only():
    assert aa.allows([aa.MANAGER], "infrastructure", write=True)
    assert aa.allows([aa.MANAGER], "audit") and not aa.allows([aa.MANAGER], "audit", write=True)


def test_everybody_may_change_their_own_password():
    assert all(aa.allows([role], "self", write=True) for role in aa.ROLES)


@pytest.mark.parametrize("roles", [None, [], ["nonsense"], [""]])
def test_no_known_role_means_no_access_at_all(roles):
    assert aa.role_of(roles) is None
    assert aa.permissions(roles) == []
    assert not any(aa.allows(roles, area) for area in aa.AREAS)


def test_first_known_role_wins():
    assert aa.role_of(["nonsense", aa.SUPPORT, aa.OWNER]) == aa.SUPPORT


def test_permissions_list_for_the_web():
    perms = aa.permissions([aa.FINANCE])
    assert "payments:rw" in perms and "reports:r" in perms and "system:rw" not in perms


def test_store_endpoints_need_matching_grants():
    assert aa.store_context_allowed([aa.OWNER], write=True)
    assert aa.store_context_allowed([aa.MANAGER], write=True)
    assert aa.store_context_allowed([aa.VIEWER], write=False) and not aa.store_context_allowed([aa.VIEWER], write=True)
    assert not aa.store_context_allowed([aa.SUPPORT], write=True)  # no catalog/reseller write
    assert not aa.store_context_allowed(None, write=False)


# ---------------------------------------------------------------- password policy
@pytest.mark.parametrize(
    "password, email, code",
    [
        ("Short1!", "a@b.co", "PASSWORD_TOO_SHORT"),
        ("x" * 129 + "A1!", "a@b.co", "PASSWORD_TOO_LONG"),
        ("aaaaaaaaaaaaaaaa", "a@b.co", "PASSWORD_REPETITIVE"),
        ("ababababababab", "a@b.co", "PASSWORD_REPETITIVE"),
        ("Xx-sara.mohammadi-9!", "sara.mohammadi@example.com", "PASSWORD_HAS_EMAIL"),
        ("password1234", "a@b.co", "PASSWORD_COMMON"),
        ("onlylowercaseletters", "a@b.co", "PASSWORD_WEAK_MIX"),
        ("ALLUPPER123456", "a@b.co", "PASSWORD_WEAK_MIX"),
    ],
)
def test_password_policy_rejects(password, email, code):
    assert pp.violation(password, email) == code
    assert code in pp.MESSAGES_FA


def test_password_policy_order_is_pinned():
    assert [code for code, _ in pp.RULES] == [
        "PASSWORD_TOO_SHORT",
        "PASSWORD_TOO_LONG",
        "PASSWORD_REPETITIVE",
        "PASSWORD_HAS_EMAIL",
        "PASSWORD_COMMON",
        "PASSWORD_WEAK_MIX",
    ]
    assert set(pp.MESSAGES_FA) == {code for code, _ in pp.RULES}


@pytest.mark.parametrize("password", ["Correct-Horse-9", "mixed Case phrase 2026", "علی-و-Reza-1404-Ok"])
def test_password_policy_accepts(password):
    assert pp.violation(password, "root@example.com") is None


def test_short_email_local_part_is_not_a_password_rule():
    assert pp.violation("Zq9-aaaa-Bbbb-cc", "ab@x.io") is None


# ---------------------------------------------------------------- guard wiring (deps.py)
class _Untouchable:
    """A session that fails the test if the guard writes anything (no audit event for a non-admin-panel session)."""

    def __getattr__(self, name):
        raise AssertionError(f"session.{name} must not be touched")


def _admin_request(path: str, method: str):
    import types

    return types.SimpleNamespace(url=types.SimpleNamespace(path=path), method=method)


async def test_role_guard_ignores_a_customer_channel_session_of_an_admin_account():
    """The role check judges admin-panel sessions only; a customer session of the same account is refused by
    ``require_admin_session`` itself, so it must neither pass here nor leave an ``admin_area_denied`` event."""
    import types

    from melorin.core import deps

    user = types.SimpleNamespace(is_super_admin=True, admin_roles=["viewer"])
    customer_session = types.SimpleNamespace(is_admin_session=False)
    await deps.admin_area_guard(_admin_request("/api/v1/admin/settings/x", "PUT"), _Untouchable(), customer_session, user)


def test_store_context_dependencies_require_the_request():
    """``request`` has no default: a missing request would silently skip the admin role check (fail open)."""
    import inspect

    from melorin.core import deps

    for dep in (deps.store_context, deps.owner_store_context):
        param = inspect.signature(dep).parameters["request"]
        assert param.default is inspect.Parameter.empty and param.kind is inspect.Parameter.KEYWORD_ONLY


# ---- sign-in methods (Google / Telegram) moved to Settings in the admin UI: the API side must stay owner-only
_LOGIN_SETTING_PATHS = [
    ("/api/v1/admin/integrations", "GET"),
    ("/api/v1/admin/integrations/google", "GET"),
    ("/api/v1/admin/integrations/google", "PUT"),
    ("/api/v1/admin/integrations/telegram", "GET"),
    ("/api/v1/admin/integrations/telegram", "PUT"),
    ("/api/v1/admin/integrations/telegram/test", "POST"),
    ("/api/v1/admin/integrations/admin-access", "PUT"),
]


@pytest.mark.parametrize("path, method", _LOGIN_SETTING_PATHS)
def test_login_settings_are_owner_only_for_every_role(path, method):
    area, write = aa.area_for(path, method)
    assert area == "system"
    for role in aa.ROLES:
        assert aa.allows([role], area, write=write) is (role == aa.OWNER)


def test_customer_identity_is_a_customers_screen_support_writes_finance_reads():
    # the identity screen (customers area) no longer hosts sign-in settings, so support may use it fully
    area, write = aa.area_for("/api/v1/admin/identity-link-reviews", "GET")
    assert area == "customers" and not write
    assert aa.allows([aa.SUPPORT], area, write=True)
    assert aa.allows([aa.FINANCE], area) and not aa.allows([aa.FINANCE], area, write=True)
