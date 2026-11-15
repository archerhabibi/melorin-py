"""Card-to-card auto verification against the bank's deposit SMS.

Flow: the store owner's phone forwards every bank SMS to ``POST /payments/bank-sms/{store_id}`` (token protected) ->
the SMS is parsed and stored once -> it is matched with a customer receipt that waits for review (same amount, the
time printed on the receipt agrees with the SMS, the SMS is not older than the request) -> only an unambiguous match
credits the wallet through the normal ``mark_succeeded`` path (row locks + ledger idempotency key, so a duplicate
SMS, a retry or a race can never credit twice). Everything else stays in the manual review queue.

Package layout: ``config`` (settings, source lookup), ``authentication`` (token + source credentials), ``matching``
(candidate selection, linking, auto-confirm), ``reconciliation`` (re-match a store backlog), ``ingestion`` (parse + store one
SMS), ``review`` (manual queue operations and claim helpers). Every public name stays importable from this package.
"""

from __future__ import annotations

from melorin.modules.payments.bank_sms.config import (
    log,
    MAX_SMS_CHARS,
    TOKEN_PREFIX,
    _SETTING_RULES,
    clean_settings,
    match_settings,
    source_out,
    get_source,
)  # noqa: F401
from melorin.modules.payments.bank_sms.authentication import hash_token, new_token, save_source, rotate_token, authenticate  # noqa: F401
from melorin.modules.payments.bank_sms.matching import P, _candidates, _notify, _link, _confirm_provisional, match_message  # noqa: F401
from melorin.modules.payments.bank_sms.reconciliation import reconcile_store, try_auto_verify_payment  # noqa: F401
from melorin.modules.payments.bank_sms.ingestion import ingest  # noqa: F401
from melorin.modules.payments.bank_sms.review import message_out, list_messages, manual_link, set_ignored, build_claim, parse_claim  # noqa: F401

__all__ = [
    "log",
    "MAX_SMS_CHARS",
    "TOKEN_PREFIX",
    "_SETTING_RULES",
    "clean_settings",
    "match_settings",
    "source_out",
    "get_source",
    "hash_token",
    "new_token",
    "save_source",
    "rotate_token",
    "authenticate",
    "P",
    "_candidates",
    "_notify",
    "_link",
    "_confirm_provisional",
    "match_message",
    "reconcile_store",
    "try_auto_verify_payment",
    "ingest",
    "message_out",
    "list_messages",
    "manual_link",
    "set_ignored",
    "build_claim",
    "parse_claim",
]
