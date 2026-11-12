"""Password policy for admin accounts (pure). Ordered rule table: the first violated rule wins, so the message is stable.

Used when an invited admin chooses a password. Existing accounts keep their password until they change it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

MIN_LENGTH = 12
MAX_LENGTH = 128

_COMMON = frozenset(
    {
        "password1234",
        "123456789012",
        "qwertyuiop12",
        "admin1234567",
        "melorin12345",
        "iloveyou1234",
        "letmein12345",
        "welcome12345",
    }
)


def _classes(password: str) -> int:
    return sum(bool(re.search(pattern, password)) for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))


def _contains_local_part(password: str, email: str) -> bool:
    local = email.split("@", 1)[0].lower()
    return len(local) >= 4 and local in password.lower()


def _single_run(password: str) -> bool:
    """``aaaaaaaaaaaa`` / ``121212121212``: one or two characters repeated."""
    return len(set(password)) <= 2


# (code, predicate that is True when the rule is VIOLATED). Order matters and is pinned by tests/unit/test_password_policy.py.
RULES: tuple[tuple[str, Callable[[str, str], bool]], ...] = (
    ("PASSWORD_TOO_SHORT", lambda p, e: len(p) < MIN_LENGTH),
    ("PASSWORD_TOO_LONG", lambda p, e: len(p) > MAX_LENGTH),
    ("PASSWORD_REPETITIVE", lambda p, e: _single_run(p)),
    ("PASSWORD_HAS_EMAIL", lambda p, e: _contains_local_part(p, e)),
    ("PASSWORD_COMMON", lambda p, e: p.lower() in _COMMON),
    ("PASSWORD_WEAK_MIX", lambda p, e: _classes(p) < 3),
)

MESSAGES_FA: dict[str, str] = {
    "PASSWORD_TOO_SHORT": f"رمز عبور باید دست‌کم {MIN_LENGTH} نویسه باشد.",
    "PASSWORD_TOO_LONG": f"رمز عبور نباید بیش از {MAX_LENGTH} نویسه باشد.",
    "PASSWORD_REPETITIVE": "رمز عبور نباید تکرار یک یا دو نویسه باشد.",
    "PASSWORD_HAS_EMAIL": "رمز عبور نباید شامل بخشی از ایمیل شما باشد.",
    "PASSWORD_COMMON": "این رمز عبور بسیار رایج است؛ رمز دیگری انتخاب کنید.",
    "PASSWORD_WEAK_MIX": "رمز عبور باید ترکیبی از حداقل سه نوع نویسه باشد: حرف کوچک، حرف بزرگ، عدد و نماد.",
}


def violation(password: str, email: str = "") -> str | None:
    """The code of the first violated rule, or ``None`` when the password is acceptable."""
    for code, violated in RULES:
        if violated(password, email):
            return code
    return None
