#!/usr/bin/env python3
"""Export Core's OpenAPI document to packages/api-client/openapi.json (Phase 6.3).

    python scripts/gen_api_client.py --write   # refresh the snapshot, then: npm run generate (packages/api-client)
    python scripts/gen_api_client.py --check   # CI: fail when the snapshot is stale

The snapshot is deterministic (sorted keys, 2-space indent) so API changes show up as reviewable diffs.
No database or Redis is touched: importing the app and calling ``app.openapi()`` is enough.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "packages" / "api-client" / "openapi.json"


def render() -> str:
    os.environ.setdefault("MELORIN_ENV", "development")
    os.environ.setdefault("MELORIN_DATABASE_URL", "postgresql+asyncpg://openapi:openapi@localhost:5432/openapi")
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from melorin.app import app  # noqa: PLC0415 - env must be set before the import

    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    fresh = render()
    if args.write:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(fresh, encoding="utf-8")
        print(f"wrote {TARGET.relative_to(ROOT)} ({len(json.loads(fresh)['paths'])} paths)")
        return 0
    if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != fresh:
        print(
            "packages/api-client/openapi.json is stale. Run:\n"
            "  python scripts/gen_api_client.py --write && (cd packages/api-client && npm run generate)",
            file=sys.stderr,
        )
        return 1
    print("api-client OpenAPI snapshot is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
