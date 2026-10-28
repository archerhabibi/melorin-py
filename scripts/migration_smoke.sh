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
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        assert version == head, (version, head)
        columns = (await conn.execute(text(
            "select column_name from information_schema.columns "
            "where table_name = 'commissions' and column_name = 'referred_user_id'"
        ))).scalars().all()
        assert columns == ["referred_user_id"], columns
        # 0037: only the sign-up reward is unique per (store, referred customer); the purchase commission is paid on every order.
        indexes = (await conn.execute(text(
            "select indexdef from pg_indexes "
            "where tablename = 'commissions' and indexname = 'uq_commissions_store_referred_signup_reward'"
        ))).scalars().all()
        assert len(indexes) == 1, indexes
        # It must be UNIQUE on (store_id, referred_user_id) and PARTIAL (sign-up reward only); a plain or non-unique index would pass a name-only check.
        assert "UNIQUE" in indexes[0] and "(store_id, referred_user_id)" in indexes[0], indexes
        assert " WHERE " in indexes[0] and "kind" in indexes[0].split(" WHERE ", 1)[1] and "signup_reward" in indexes[0].split(" WHERE ", 1)[1], indexes
        stale = (await conn.execute(text(
            "select constraint_name from information_schema.table_constraints "
            "where table_name = 'commissions' and constraint_name in "
            "('uq_commissions_referred_user_id_kind', 'uq_commissions_store_id_referred_user_id_kind')"
        ))).scalars().all()
        assert stale == [], stale
        stores = (await conn.execute(text("select count(*) from store_products"))).scalar_one()
        groups = (await conn.execute(text("select count(*) from bundles"))).scalar_one()
        assert groups >= 0
        assert stores >= 0
        print("migration smoke passed:", version)

asyncio.run(main())
PY
