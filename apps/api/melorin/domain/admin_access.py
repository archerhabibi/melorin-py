"""Admin team access control: roles, permission areas and the request-path -> area rule table (pure, no I/O).

Every admin-panel session belongs to a user with ``is_super_admin`` (the gate for the admin channel, password + TOTP login).
*What* that admin may do is decided by the role stored in ``users.admin_roles``:

* a role grants each **area** either read (``r``) or read+write (``rw``);
* every admin request is mapped to an area by ``PATH_RULES`` (ordered, first match wins) and to a level by its HTTP method
  (GET/HEAD = read, everything else = write; a few GETs that reveal secrets are declared as writes);
* a path no rule knows falls into ``system`` (owner only): a new admin route can be too strict, never too open;
* an admin whose role list is empty or unknown has no access at all (fail closed). ``0055_admin_team`` gives every existing
  admin the ``owner`` role, so nobody loses access on upgrade.

Design notes and the permission matrix: docs/24-Admin-Team-Design.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

OWNER, MANAGER, FINANCE, SUPPORT, VIEWER = "owner", "manager", "finance", "support", "viewer"
ROLES: tuple[str, ...] = (OWNER, MANAGER, FINANCE, SUPPORT, VIEWER)

# Permission areas (the unit a role is granted). ``self`` is what every admin may do to their own account.
AREAS: tuple[str, ...] = (
    "overview",
    "reports",
    "orders",
    "payments",
    "catalog",
    "infrastructure",
    "resellers",
    "customers",
    "support",
    "audit",
    "system",
    "admins",
    "self",
)
FALLBACK_AREA = "system"
READ, WRITE = "r", "rw"

_ALL_OPERATIONAL = ("overview", "reports", "orders", "payments", "catalog", "infrastructure", "resellers", "customers", "support")

GRANTS: dict[str, dict[str, str]] = {
    OWNER: {area: WRITE for area in AREAS},
    MANAGER: {**{a: WRITE for a in _ALL_OPERATIONAL}, "audit": READ, "self": WRITE},
    FINANCE: {
        "overview": READ,
        "reports": READ,
        "orders": WRITE,
        "payments": WRITE,
        "catalog": READ,
        "resellers": READ,
        "customers": READ,
        "self": WRITE,
    },
    SUPPORT: {
        "overview": READ,
        "orders": READ,
        "payments": READ,
        "catalog": READ,
        "customers": WRITE,
        "support": WRITE,
        "self": WRITE,
    },
    VIEWER: {**{a: READ for a in _ALL_OPERATIONAL}, "self": WRITE},
}

# (pattern, area, force_write). Paths are matched without the ``/api/v1`` prefix and without a leading slash. First match wins.
PATH_RULES: tuple[tuple[re.Pattern[str], str, bool], ...] = tuple(
    (re.compile(pattern), area, force_write)
    for pattern, area, force_write in (
        # a GET that reveals a secret is a write-level operation
        (r"^admin/panel-admins/[^/]+/credentials$", "infrastructure", True),
        (r"^admin/panels/[^/]+/service-access(/|$)", "infrastructure", True),
        (r"^admin/stores/[^/]+/bank-sms/token$", "payments", True),
        # the admin team itself, and each admin's own account
        (r"^admin/admins(/|$)", "admins", False),
        (r"^admin/me$", "self", False),
        (r"^auth/admin/password$", "self", False),
        # platform-wide settings and integrations: owner only
        (r"^admin/(settings|integrations|feature-flags)(/|$)", "system", False),
        (r"^admin/audit(/|$)", "audit", False),
        (r"^admin/(dashboard|health)(/|$)", "overview", False),
        (r"^(admin/)?reports(/|$)", "reports", False),
        (r"^admin/orders(/|$)", "orders", False),
        (r"^admin/(payments|stores/[^/]+/(bank-sms|receipt-review|receipt-duplicates))(/|$)", "payments", False),
        (
            r"^admin/(products|bundles|bundle-products|coupons|referral-rules|stores/[^/]+/(referrals|reseller-prices))(/|$)",
            "catalog",
            False,
        ),
        (
            r"^admin/(panels|servers|panel-admins|panel-admin-requests|panel-backups|panel-orphans|reconciliation|bulk-operations|operations"
            r"|store-admins|stores/[^/]+/(sub-branding|vpn-notices|vpn-notice-texts|vpn-digest))(/|$)",
            "infrastructure",
            False,
        ),
        (r"^admin/(resellers|reseller-applications|reseller-stores|bot-store-bindings|stores)(/|$)", "resellers", False),
        (
            r"^admin/(users|vpn-accounts|identity-link-reviews|identity-auto-merges|trusted-devices|manual-tasks|broadcasts|event-center)(/|$)",
            "customers",
            False,
        ),
        (r"^admin/tickets(/|$)", "support", False),
    )
)

_PREFIX = re.compile(r"^/?(?:api/v1/)?")
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def normalise(path: str) -> str:
    """``/api/v1/admin/panels/1/state`` -> ``admin/panels/1/state`` (query strings and a trailing slash are ignored)."""
    return _PREFIX.sub("", path.split("?", 1)[0]).rstrip("/")


def area_for(path: str, method: str = "GET") -> tuple[str, bool]:
    """The permission area of a request and whether it needs write access."""
    clean = normalise(path)
    write = method.upper() not in _READ_METHODS
    for pattern, area, force_write in PATH_RULES:
        if pattern.match(clean):
            return area, write or force_write
    return FALLBACK_AREA, write


def role_of(roles: Iterable[str] | None) -> str | None:
    """The effective role of an ``admin_roles`` list: the first known role (an empty or unknown list has none)."""
    for role in roles or ():
        if role in GRANTS:
            return role
    return None


def level(roles: Iterable[str] | None, area: str) -> str | None:
    role = role_of(roles)
    return GRANTS[role].get(area) if role else None


def allows(roles: Iterable[str] | None, area: str, *, write: bool = False) -> bool:
    granted = level(roles, area)
    if granted is None:
        return False
    return granted == WRITE or not write


def permissions(roles: Iterable[str] | None) -> list[str]:
    """Flat ``area:r`` / ``area:rw`` list of what a role may do (what the admin web uses to hide screens it cannot open)."""
    role = role_of(roles)
    if not role:
        return []
    return [f"{area}:{grant}" for area, grant in GRANTS[role].items()]


def is_owner(roles: Iterable[str] | None) -> bool:
    return role_of(roles) == OWNER


def store_context_allowed(roles: Iterable[str] | None, *, write: bool) -> bool:
    """An admin-channel session may act inside a store (reseller panel, loyalty, referral programs) only with the same grants
    that the matching admin screens need: a viewer cannot write through the store endpoints."""
    return allows(roles, "resellers", write=write) and allows(roles, "catalog", write=write)
