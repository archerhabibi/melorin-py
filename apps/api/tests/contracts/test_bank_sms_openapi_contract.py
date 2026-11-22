"""Bank SMS settings/source API contract: typed responses, defaults owned by the domain, and a well-formed snapshot."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from melorin.domain import bank_sms as dom
from melorin.modules.payments import bank_sms
from melorin.modules.payments.schemas import BankSmsSettingsIn, BankSmsSettingsOut, BankSmsSourceOut

SNAPSHOT = Path(__file__).resolve().parents[4] / "packages" / "api-client" / "openapi.json"
BANK_SMS_ROUTES = (
    ("get", "/api/v1/admin/stores/{store_id}/bank-sms", "BankSmsOverviewOut"),
    ("put", "/api/v1/admin/stores/{store_id}/bank-sms/source", "BankSmsSourceSavedOut"),
    ("post", "/api/v1/admin/stores/{store_id}/bank-sms/token", "BankSmsTokenOut"),
    ("post", "/api/v1/admin/stores/{store_id}/bank-sms/{sms_id}/link", "BankSmsMessageOut"),
    ("post", "/api/v1/admin/stores/{store_id}/bank-sms/{sms_id}/ignore", "BankSmsMessageOut"),
    ("get", "/api/v1/stores/{store_id}/reseller/bank-sms", "BankSmsOverviewOut"),
    ("put", "/api/v1/stores/{store_id}/reseller/bank-sms/source", "BankSmsSourceSavedOut"),
    ("post", "/api/v1/stores/{store_id}/reseller/bank-sms/token", "BankSmsTokenOut"),
    ("post", "/api/v1/stores/{store_id}/reseller/bank-sms/{sms_id}/link", "BankSmsMessageOut"),
    ("post", "/api/v1/stores/{store_id}/reseller/bank-sms/{sms_id}/ignore", "BankSmsMessageOut"),
)


def _snapshot() -> dict:
    # A snapshot with leftover bytes after the closing brace is invalid JSON and silently breaks client generation.
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_openapi_snapshot_is_well_formed_json():
    assert "paths" in _snapshot()


def test_bank_sms_routes_have_typed_responses_in_snapshot():
    paths = _snapshot()["paths"]
    for method, path, model in BANK_SMS_ROUTES:
        schema = paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema == {"$ref": f"#/components/schemas/{model}"}, (method, path)


def test_settings_schema_covers_every_domain_rule_and_documents_its_range():
    props = BankSmsSettingsIn.model_json_schema()["properties"]
    assert set(props) == {key for key, *_ in dom.SETTING_RULES}
    for key, (lo, hi) in dom.SETTING_RANGES.items():
        if lo is not None:
            assert f"{lo} to {hi}" in props[key]["description"], key
    assert set(BankSmsSettingsOut.model_fields) == set(props)


def test_source_out_for_an_unconfigured_store_uses_the_domain_defaults():
    store_id = uuid.uuid4()
    out = BankSmsSourceOut.model_validate(bank_sms.source_out(None, store_id=store_id))
    defaults = dom.MatchSettings()
    assert out.configured is False
    assert out.settings.window_minutes == defaults.window_minutes
    assert out.settings.time_tolerance_minutes == defaults.time_tolerance_minutes
    assert out.settings.require_claimed_time is defaults.require_claimed_time
    assert out.settings.max_auto_amount_rial is None and out.settings.account_number is None


def test_source_out_never_exposes_the_token_and_keeps_stored_overrides():
    src = SimpleNamespace(
        store_id=uuid.uuid4(),
        bank="mehr_iran",
        is_enabled=True,
        auto_verify=True,
        token_hash="a" * 64,
        token_hint="wxyz",
        senders=["MehrIran"],
        settings={"window_minutes": 30, "account_number": "12345678"},
        last_received_at=None,
    )
    raw = bank_sms.source_out(src)
    out = BankSmsSourceOut.model_validate(raw)
    assert out.has_token is True and out.token_hint == "wxyz"
    assert out.settings.window_minutes == 30 and out.settings.account_number == "12345678"
    assert out.settings.time_tolerance_minutes == dom.MatchSettings().time_tolerance_minutes
    assert "token_hash" not in out.model_dump() and "token" not in out.model_dump()


def test_match_settings_and_source_out_agree_on_defaults():
    src = SimpleNamespace(settings=None)
    effective = bank_sms.match_settings(src)
    shown = bank_sms.source_out(None, store_id=uuid.uuid4())["settings"]
    assert effective.window_minutes == shown["window_minutes"]
    assert effective.time_tolerance_minutes == shown["time_tolerance_minutes"]
    assert effective.require_claimed_time == shown["require_claimed_time"]
    assert effective.max_auto_amount_rial == shown["max_auto_amount_rial"]
