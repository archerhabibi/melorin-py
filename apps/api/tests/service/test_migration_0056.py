"""Alembic 0056 turns the old global card/Zarinpal settings into main-store configuration rows, once."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import melorin.models  # noqa: F401
from melorin.core.crypto import decrypt
from melorin.core.db import Base
from melorin.kernel.models.stores import Store, StorePaymentConfiguration
from melorin.kernel.models.system import SystemSetting

PATH = Path(__file__).resolve().parents[2] / "alembic/versions/0056_main_store_payment_config.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0056", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(engine):
    mod = _migration()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()


def _engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_legacy_settings_become_main_store_rows_and_are_removed():
    engine = _engine()
    with Session(engine) as s:
        s.add(Store(kind="main", slug="main", name="Main", currency="IRT"))
        s.add(SystemSetting(key="card.info", value={"card_number": "6037", "holder": "Ali", "bank": "melli"}))
        s.add(SystemSetting(key="gateway.zarinpal", value={"merchant_id": "m-1", "sandbox": True}))
        s.add(SystemSetting(key="referral.commission_bp", value=700))
        s.commit()
    _run(engine)
    _run(engine)  # idempotent
    with Session(engine) as s:
        rows = {r.provider: r for r in s.scalars(select(StorePaymentConfiguration)).all()}
        assert set(rows) == {"manual_card", "zarinpal"}
        assert rows["manual_card"].public_config["card_number"] == "6037" and rows["manual_card"].secret_enc is None
        assert rows["zarinpal"].public_config == {"sandbox": True}
        assert json.loads(decrypt(rows["zarinpal"].secret_enc)) == {"merchant_id": "m-1"}
        keys = set(s.scalars(select(SystemSetting.key)).all())
        assert keys == {"referral.commission_bp"}


def test_existing_row_is_not_overwritten_and_empty_database_is_fine():
    empty = _engine()
    _run(empty)  # no main store, no settings
    engine = _engine()
    with Session(engine) as s:
        main = Store(kind="main", slug="main", name="Main", currency="IRT")
        s.add(main)
        s.flush()
        s.add(StorePaymentConfiguration(store_id=main.id, provider="manual_card", public_config={"card_number": "NEW", "holder": "h"}))
        s.add(SystemSetting(key="card.info", value={"card_number": "OLD", "holder": "h"}))
        s.commit()
    _run(engine)
    with Session(engine) as s:
        (row,) = s.scalars(select(StorePaymentConfiguration)).all()
        assert row.public_config["card_number"] == "NEW"
