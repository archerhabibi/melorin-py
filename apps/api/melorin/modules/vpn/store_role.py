"""PG-12 / L6: the role a store's panel admin should hold (``melorin-store``). PLAN ONLY in this release.

Today store admins are created with the panel's stock ``operator`` role, which on the live panel carries ``api_keys`` (read/update/
delete, own scope): a reseller's admin could change or delete its own keys, which has no use for Melorin. This module states the
smallest permission set a store admin needs so an operator can create that role on the panel and compare it with ``operator``.

It deliberately does **not** write to the panel: the role request shape is known from the 5.6.0 contract, but it has not been applied
to a live panel from this work (decision 3: Melorin does not write panel settings without an approved case). Switching
``panel_admins.ROLE`` to ``melorin-store`` is the follow-up once the role exists on staging.
"""

from __future__ import annotations

STORE_ROLE_NAME = "melorin-store"
# Create / read / change / remove the store's own customers, and read the groups it may place them in. Nothing else.
STORE_PERMISSIONS = ("users.create", "users.read", "users.update", "users.delete", "groups.read")
WITHHELD = ("api_keys.*", "admins.*", "nodes.*", "hosts.*", "groups.create/update/delete", "cores.*", "settings.*")


def role_body() -> dict:
    perms: dict[str, dict[str, bool]] = {}
    for path in STORE_PERMISSIONS:
        section, _, action = path.partition(".")
        perms.setdefault(section, {})[action] = True
    return {"name": STORE_ROLE_NAME, "permissions": perms, "features": {}}


def plan(current_role: str = "operator") -> dict:
    return {
        "role": STORE_ROLE_NAME,
        "replaces": current_role,
        "grants": list(STORE_PERMISSIONS),
        "withheld": list(WITHHELD),
        "applied_by_melorin": False,
        "how": "Create the role on the panel with `body`, assign one test store admin, check a create/renew/delete round trip, then roll out.",
        "body": role_body(),
    }
