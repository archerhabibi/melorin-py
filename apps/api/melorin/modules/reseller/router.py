"""Reseller API composition root.

The former 768-line router now lives in one module per route family under ``reseller/routes/``
(applications, store_profile, pricing, customers, accounts, store_payments, credentials, webhook_endpoints and the
versioned ``public_api``). Paths, methods and schemas are unchanged; this module only assembles them.
"""

from fastapi import APIRouter

from melorin.modules.reseller.routes import (
    accounts,
    applications,
    credentials,
    customers,
    pricing,
    store_payments,
    store_profile,
    webhook_endpoints,
)
from melorin.modules.reseller.routes.public_api import api_router

router = APIRouter(tags=["reseller"])
# The families carry their own tag; their routes are attached directly (not wrapped) so ``router.routes`` lists every
# reseller endpoint with its final path, in the same order as before the split.
for _family in (applications, store_profile, pricing, customers, accounts, store_payments, credentials, webhook_endpoints):
    router.routes.extend(_family.router.routes)

__all__ = ["router", "api_router"]

# Backward-compatible attribute access (``from melorin.modules.reseller.router import apply``) for callers and tests
# written before the split. New code should import from the family module directly.
_FAMILIES = (
    "applications",
    "store_profile",
    "pricing",
    "customers",
    "accounts",
    "store_payments",
    "credentials",
    "webhook_endpoints",
    "public_api",
)


def __getattr__(name: str):
    import importlib

    for family in _FAMILIES:
        module = importlib.import_module(f"melorin.modules.reseller.routes.{family}")
        if name in vars(module):
            return getattr(module, name)
    raise AttributeError(name)
