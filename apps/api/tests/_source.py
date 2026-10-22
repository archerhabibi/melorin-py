"""Formatter-stable access to source files for "contract" tests (M6.7).

Several tests assert that a snippet exists in a source file. Comparing raw text
makes them break whenever ``ruff format`` re-wraps a line or adds a trailing
comma. ``read_source`` normalises layout-only differences so such assertions
only fail when the *code* changes.

Prefer behavioural assertions (import the object and inspect it) for new tests;
use ``read_source`` only where the property truly is "this text is in that file".
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_WS = re.compile(r"\s+")
_AFTER_OPEN = re.compile(r"([(\[{])\s+")
_BEFORE_CLOSE = re.compile(r"\s+([)\]}])")
_TRAILING_COMMA = re.compile(r",\s*([)\]}])")


def normalize_source(text: str) -> str:
    """Collapse whitespace and drop layout-only punctuation (wrapping, trailing commas)."""
    text = _WS.sub(" ", text)
    text = _TRAILING_COMMA.sub(r"\1", text)
    text = _AFTER_OPEN.sub(r"\1", text)
    text = _BEFORE_CLOSE.sub(r"\1", text)
    return text.strip()


# Phase 3.3: the admin API router is split into one module per route family. Contract tests that ask for
# ``modules/admin/router.py`` get the text of the whole family (composition root + route modules).
ADMIN_ROUTE_MODULES = (
    "router",
    "overview",
    "products",
    "panels",
    "bundles",
    "payments",
    "orders",
    "directory",
    "tickets",
    "reseller_applications",
    "settings",
    "coupons",
    "identity_reviews",
    "_common",
)


# Phase 3.8: the reseller API router is split the same way (``modules/reseller/routes/<family>.py``).
RESELLER_ROUTE_MODULES = (
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


def _is_reseller_router(path: Path) -> bool:
    return path.name == "router.py" and path.parent.name == "reseller" and path.parent.parent.name == "modules"


def _is_admin_router(path: Path) -> bool:
    return path.name == "router.py" and path.parent.name == "admin" and path.parent.parent.name == "modules"


def _is_identity_router(path: Path) -> bool:
    return path.name == "router.py" and path.parent.name == "identity" and path.parent.parent.name == "modules"


def _is_app_entry(path: Path) -> bool:
    return path.name == "app.py" and path.parent.name == "melorin"


def _is_main_bot_runner(path: Path) -> bool:
    return path.name == "runner.py" and path.parent.name == "telegram-main"


def _is_reseller_bot_runner(path: Path) -> bool:
    return path.name == "runner.py" and path.parent.name == "telegram-reseller"


def _raw_text(path: Path) -> str:
    """Raw text of ``path``; split entry points resolve to the whole family (Phase 3.3 admin router, Phase 3.4 main bot, Phase 3.15 reseller bot)."""
    path = Path(path)
    if _is_admin_router(path):
        return "\n".join((path.parent / f"{name}.py").read_text(encoding="utf-8") for name in ADMIN_ROUTE_MODULES)
    if _is_reseller_router(path):
        parts = [path.read_text(encoding="utf-8")]
        parts += [(path.parent / "routes" / f"{name}.py").read_text(encoding="utf-8") for name in RESELLER_ROUTE_MODULES]
        return "\n".join(parts)
    if _is_app_entry(path):  # Phase 3.17: app.py + core/health.py (readiness probes)
        return "\n".join(f.read_text(encoding="utf-8") for f in (path, path.parent / "core" / "health.py"))
    if _is_main_bot_runner(path):
        parts = [path.read_text(encoding="utf-8")]
        parts += [f.read_text(encoding="utf-8") for f in sorted((path.parent / "tgmain").rglob("*.py"))]
        return "\n".join(parts)
    if _is_identity_router(path):  # Phase 3.16: router.py + routes/{_common,sign_in,account}.py
        parts = [path.read_text(encoding="utf-8")]
        parts += [f.read_text(encoding="utf-8") for f in sorted((path.parent / "routes").rglob("*.py"))]
        return "\n".join(parts)
    if _is_reseller_bot_runner(path):  # Phase 3.15: runner.py + tgreseller/{bot,hosting}.py
        parts = [path.read_text(encoding="utf-8")]
        parts += [f.read_text(encoding="utf-8") for f in sorted((path.parent / "tgreseller").rglob("*.py"))]
        return "\n".join(parts)
    if not path.exists() and path.suffix == ".py" and path.with_suffix("").is_dir():  # a module that became a package
        return "\n".join(f.read_text(encoding="utf-8") for f in sorted(path.with_suffix("").rglob("*.py")))
    return path.read_text(encoding="utf-8")


def read_source(path: str | Path) -> str:
    """Return the normalised text of a Python source file (the admin router resolves to all its route modules)."""
    return normalize_source(_raw_text(Path(path)))


def parse_source(path: str | Path) -> ast.Module:
    """Parse a Python file from its *raw* text (normalised text is not valid Python)."""
    return ast.parse(Path(path).read_text(encoding="utf-8"))
