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
        assert version == "0009_referral_first_reward_guard", version
        columns = (await conn.execute(text(
            "select column_name from information_schema.columns "
            "where table_name = 'commissions' and column_name = 'referred_user_id'"
        ))).scalars().all()
        assert columns == ["referred_user_id"], columns
        constraints = (await conn.execute(text(
            "select constraint_name from information_schema.table_constraints "
            "where table_name = 'commissions' and constraint_name = 'uq_commissions_referred_user_id_kind'"
        ))).scalars().all()
        assert constraints == ["uq_commissions_referred_user_id_kind"], constraints
        print("migration smoke passed:", version)

asyncio.run(main())
PY
