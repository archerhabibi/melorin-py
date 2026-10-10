"""Verified-email auto-linking decision (doc 06 v1.1). Pure decision, executed by identity service.

- verified email matches exactly one existing User and the incoming identity is not attached elsewhere => link
- matches nobody => create/keep
- several Users, or the incoming identity already belongs to a *different* User with its own data => conflict:
  never auto-merge; open a manual review item and audit it.
"""
from dataclasses import dataclass
from enum import StrEnum


class Decision(StrEnum):
    LINK = "link"
    NEW = "new"
    ALREADY = "already"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class Candidate:
    user_id: str
    has_records: bool = False  # orders, wallet entries, vpn accounts


def decide(*, email_verified: bool, matches: list[Candidate], current_user_id: str | None) -> tuple[Decision, str | None]:
    if not email_verified:
        return (Decision.NEW, current_user_id) if current_user_id else (Decision.NEW, None)
    ids = {c.user_id for c in matches}
    if current_user_id and ids <= {current_user_id}:
        return Decision.ALREADY, current_user_id
    if len(ids) > 1:
        return Decision.CONFLICT, None
    if not ids:
        return Decision.NEW, current_user_id
    target = next(iter(ids))
    if current_user_id is None:
        return Decision.LINK, target
    # Two distinct existing users. Only auto-attach when the current one is an empty shell.
    return Decision.CONFLICT, target
