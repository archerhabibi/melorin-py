"""Pure rules of Person / Account / Login-Identity linking (docs/25). No I/O: the service layer loads facts and applies decisions.

The non-negotiable invariants, in one place so every channel (site, Telegram bot, admin) gets the same answer:

* one active Telegram login per person; a Telegram id / Google sub / e-mail belongs to one person at a time;
* any number of Google and e-mail logins per person;
* nothing is ever merged because of a shared e-mail, name, IP or device: only an explicit, proven, confirmed action links;
* a person can never be left with no way to sign in;
* linking identities never moves money. Moving money is a separate, ledgered, idempotent consolidation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

PROVIDERS = ("telegram", "google", "email")
SINGLE_ACTIVE = frozenset({"telegram"})  # providers limited to one active identity per person


class OpStatus(StrEnum):
    CANDIDATE = "candidate"  # a possible relation was spotted; ownership NOT proven; grants no access
    PENDING = "pending_verification"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"


class OpType(StrEnum):
    LINK = "link"
    UNLINK = "unlink"
    REPLACE = "replace"
    MERGE = "merge"


class Evidence(StrEnum):
    SESSION = "session"  # signed in to the destination account
    OAUTH_GOOGLE = "oauth_google"
    EMAIL_CODE = "email_code"
    TELEGRAM_BOT = "telegram_bot"
    LINK_TOKEN = "link_token"
    ADMIN_REVIEW = "admin_review"


# Evidence that proves control of the *identity being attached* (a session only proves the destination account).
PROVES_IDENTITY = frozenset({Evidence.OAUTH_GOOGLE, Evidence.EMAIL_CODE, Evidence.TELEGRAM_BOT})


class Verdict(StrEnum):
    ATTACH = "attach"  # free identity: attach to this person
    ALREADY = "already"  # already active on this person: idempotent success
    REACTIVATE = "reactivate"  # a revoked row of this identity is free to come back
    CONFLICT = "conflict"  # active on another person: needs the confirmed person-link flow
    REFUSE_TELEGRAM_LIMIT = "refuse_telegram_limit"  # person already has another active Telegram: use replace
    REFUSE_UNPROVEN = "refuse_unproven"


@dataclass(frozen=True)
class IdentityFacts:
    """What the database says about the identity someone wants to attach."""

    exists: bool = False
    active: bool = False
    person_id: str | None = None


def decide_attach(
    *,
    provider: str,
    target_person_id: str,
    identity: IdentityFacts,
    person_active_providers: dict[str, int],
    evidence: frozenset[Evidence],
) -> Verdict:
    """May this identity be attached to ``target_person_id``? ``person_active_providers`` = active identities per provider."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    if not (evidence & PROVES_IDENTITY):
        return Verdict.REFUSE_UNPROVEN  # a signed-in session or a typed-in username proves nothing about the identity
    if identity.exists and identity.active:
        if identity.person_id == target_person_id:
            return Verdict.ALREADY
        return Verdict.CONFLICT  # never silently moved from one person to another
    if provider in SINGLE_ACTIVE and person_active_providers.get(provider, 0) >= 1:
        return Verdict.REFUSE_TELEGRAM_LIMIT
    return Verdict.REACTIVATE if identity.exists else Verdict.ATTACH


def can_unlink(*, active_methods: int, is_target_last_usable: bool, target_provider: str, target_is_active: bool) -> tuple[bool, str]:
    """Unlinking must leave at least one other usable sign-in on the person."""
    if not target_is_active:
        return False, "not_active"
    if active_methods <= 1 or is_target_last_usable:
        return False, "last_login_method"
    return True, "ok"


def telegram_conflict_resolution(source_has_tg: bool, target_has_tg: bool, keep: str | None) -> tuple[str, str | None]:
    """Linking two persons that both own an active Telegram. ``keep`` is the user's explicit choice: target | source.
    Returns (action, revoke_side): action ok | need_choice."""
    if not (source_has_tg and target_has_tg):
        return "ok", None
    if keep not in {"target", "source"}:
        return "need_choice", None
    return "ok", "source" if keep == "target" else "target"


# --------------------------------------------------------------------------------------------- consolidation
@dataclass(frozen=True)
class WalletFacts:
    wallet_id: str
    user_id: str
    store_id: str
    currency: str
    balance: int


@dataclass(frozen=True)
class Blocker:
    code: str
    user_id: str | None = None
    detail: str | None = None


@dataclass
class Plan:
    transfers: list[tuple[str, str, int, str]] = field(default_factory=list)  # (source_wallet, target_wallet, amount, currency)
    blockers: list[Blocker] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers


def plan_consolidation(
    *,
    central_user_id: str,
    sources: list[WalletFacts],
    central_wallets: dict[tuple[str, str], str],
    pending_by_user: dict[str, list[str]],
) -> Plan:
    """Wallets are never merged across stores or currencies (store isolation): each (store, currency) is its own pool.

    Blockers (any one stops the whole operation, accounts stay linked): a negative balance (debt), or anything still in flight
    for an account (pending payment, refund, order). Zero balances need no transfer, only the routing change.
    ``central_wallets`` maps (store_id, currency) -> wallet id of the central account."""
    plan = Plan()
    for uid, reasons in sorted(pending_by_user.items()):
        for r in reasons:
            plan.blockers.append(Blocker(r, uid))
    for w in sources:
        if w.user_id == central_user_id:
            continue
        if w.balance < 0:
            plan.blockers.append(Blocker("negative_balance", w.user_id, f"{w.store_id}:{w.currency}"))
            continue
        if w.balance == 0:
            continue
        target = central_wallets.get((w.store_id, w.currency))
        if target is None:
            plan.blockers.append(Blocker("central_wallet_missing", w.user_id, f"{w.store_id}:{w.currency}"))
            continue
        plan.transfers.append((w.wallet_id, target, w.balance, w.currency))
    return plan
