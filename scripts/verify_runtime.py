"""Fail-fast runtime preflight for H001.

This intentionally checks imports and app construction without starting a
server or contacting external providers.
"""
from importlib import import_module
from pathlib import Path
import os


REQUIRED = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "asyncpg",
    "alembic",
    "pydantic_settings",
    "jwt",
    "cryptography",
    "httpx",
    "multipart",
    "redis",
    "arq",
)

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

for name in REQUIRED:
    import_module(name)

import sys

sys.path.insert(0, str(ROOT / "apps/api"))
import_module("melorin.app")
print(f"runtime preflight passed: {len(REQUIRED)} dependencies and Core app import")
