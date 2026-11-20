import pytest
from pydantic import ValidationError

from melorin.modules.payments.schemas import BankSmsSettingsIn, BankSmsSourceIn


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"window_minutes": 5}, {"window_minutes": 5}),
        ({"window_minutes": 10080}, {"window_minutes": 10080}),
        ({"time_tolerance_minutes": 0}, {"time_tolerance_minutes": 0}),
        ({"require_claimed_time": False}, {"require_claimed_time": False}),
        ({"max_auto_amount_rial": 10**13}, {"max_auto_amount_rial": 10**13}),
        ({"account_number": "۱۲۳۴۵۶۷۸"}, {"account_number": "۱۲۳۴۵۶۷۸"}),
        ({"window_minutes": None}, {"window_minutes": None}),
    ],
)
def test_bank_sms_settings_accept_supported_values(payload, expected):
    assert (
        BankSmsSettingsIn.model_validate(payload).model_dump(exclude_unset=True)
        == expected
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"window_minutes": True},
        {"time_tolerance_minutes": False},
        {"require_claimed_time": 1},
        {"max_auto_amount_rial": True},
        {"unknown_setting": 1},
    ],
)
def test_bank_sms_settings_reject_invalid_values(payload):
    with pytest.raises(ValidationError):
        BankSmsSettingsIn.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"window_minutes": 4},
        {"window_minutes": 10081},
        {"time_tolerance_minutes": -1},
        {"time_tolerance_minutes": 31},
        {"max_auto_amount_rial": 0},
        {"max_auto_amount_rial": 10**13 + 1},
    ],
)
def test_bank_sms_schema_leaves_domain_ranges_to_business_validation(payload):
    # Request-schema bounds would mask the stable BANK_SMS_SETTING_INVALID domain error.
    assert (
        BankSmsSettingsIn.model_validate(payload).model_dump(exclude_unset=True)
        == payload
    )


def test_bank_sms_source_settings_are_typed_and_nullable_for_reset():
    source = BankSmsSourceIn.model_validate(
        {"settings": {"window_minutes": None, "require_claimed_time": True}}
    )
    assert source.model_dump(exclude_unset=True) == {
        "settings": {"window_minutes": None, "require_claimed_time": True}
    }
    assert BankSmsSourceIn.model_validate({"settings": None}).settings is None


def test_bank_sms_source_rejects_unknown_nested_settings():
    with pytest.raises(ValidationError):
        BankSmsSourceIn.model_validate({"settings": {"arbitrary": "value"}})
