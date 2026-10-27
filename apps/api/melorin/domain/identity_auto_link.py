"""Automatic resolution of identity-link conflicts (docs/21). Pure decision; the identity service executes it.

A conflict (the same verified identity pointing at two accounts) used to wait for an admin. It is now settled by itself
whenever that is provably safe, and only the genuinely ambiguous cases still reach a human:

* exactly two accounts are involved, both active and neither an admin;
* at least one of them is an *empty shell* (no orders, payments, VPN accounts, tickets, balance, referral or any other
  business record, no password, no 2FA): nothing of value can be lost by folding it into the other;
* the account that keeps living is the one with records; when both are shells, the older one.

Two accounts that both hold records are never merged automatically.
"""

from dataclasses import dataclass
from enum import StrEnum


class Outcome(StrEnum):
    MERGE = "merge"  # fold `shell` into `keeper`
    MANUAL = "manual"  # leave for an admin


@dataclass(frozen=True)
class Account:
    user_id: str
    is_shell: bool  # no business records, no credentials
    eligible: bool  # active and not an admin
    created_rank: int = 0  # smaller = older (any monotonic number, e.g. a timestamp)


@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    keeper: str | None = None
    shell: str | None = None
    reason: str = ""


def resolve(a: Account, b: Account) -> Resolution:
    if a.user_id == b.user_id:
        return Resolution(Outcome.MANUAL, reason="same_account")
    if not (a.eligible and b.eligible):
        return Resolution(Outcome.MANUAL, reason="account_not_eligible")
    if a.is_shell and b.is_shell:
        keeper, shell = (a, b) if a.created_rank <= b.created_rank else (b, a)
        return Resolution(Outcome.MERGE, keeper.user_id, shell.user_id, "both_shells_keep_older")
    if a.is_shell:
        return Resolution(Outcome.MERGE, b.user_id, a.user_id, "source_is_shell")
    if b.is_shell:
        return Resolution(Outcome.MERGE, a.user_id, b.user_id, "candidate_is_shell")
    return Resolution(Outcome.MANUAL, reason="both_have_records")
