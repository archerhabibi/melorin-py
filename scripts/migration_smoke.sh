#!/usr/bin/env bash
set -euo pipefail

# H002: fresh-install and head verification. Run inside the API environment.
: "${MELORIN_DATABASE_URL:?MELORIN_DATABASE_URL is required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/apps/api"
alembic upgrade head
alembic current
alembic heads
python - <<'PY'
import asyncio
from sqlalchemy import text
from melorin.core.db import engine

async def main():
    async with engine().begin() as conn:
        result = await conn.execute(text("select version_num from alembic_version"))
        version = result.scalar_one()
        assert version == "0008_bot_store_bindings", version
        print("migration smoke passed:", version)

asyncio.run(main())
PY
