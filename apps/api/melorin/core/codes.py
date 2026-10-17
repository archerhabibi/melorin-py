"""Customer-facing short codes: always exactly 6 characters.

Layout
------
  positions 0-3 (prefix, 4 chars)  — encoded from a monotonically increasing
    DB sequence.  The prefix preserves rough creation order and gives admins an
    easy visual sort, but is NOT a raw integer, so it is not trivially
    guessable by customers.
  positions 4-5 (suffix, 2 chars)  — cryptographically random from the same
    alphabet.  32² = 1 024 combinations per prefix; brute-forcing a code is
    computationally feasible but operationally meaningless (wrong code = 404).

Alphabet
--------
  32 symbols, visually unambiguous (no 0/O, 1/I/l):
      2 3 4 5 6 7 8 9 A B C D E F G H J K L M N P Q R S T U V W X Y Z

Uniqueness
----------
  A DB UNIQUE constraint is the single source of truth.  The 4-char prefix
  comes from a unique sequence value, so codes cannot collide until the
  sequence wraps after 32^4 = 1 048 576 values; after that the random suffix
  gives only 1/1024 odds of avoiding a clash and the UNIQUE constraint rejects
  duplicates.  No automatic retry is implemented.
"""

import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

ORDER_SEQ = "order_number_seq"
TICKET_SEQ = "ticket_number_seq"

# 32 visually unambiguous symbols (no 0/O, 1/I/l)
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
SEQ_WIDTH = 4  # carries monotonic ordering
RAND_WIDTH = 2  # anti-guessing entropy
CODE_LEN = SEQ_WIDTH + RAND_WIDTH  # 6
_BASE = len(ALPHABET)  # 32
_MAX_SEQ = _BASE**SEQ_WIDTH  # 32^4 = 1 048 576


def _encode(n: int, width: int) -> str:
    """Encode *n* in base-32 (ALPHABET), fixed *width*, big-endian."""
    out: list[str] = []
    for _ in range(width):
        n, r = divmod(n, _BASE)
        out.append(ALPHABET[r])
    return "".join(reversed(out))


async def next_code(session: AsyncSession, sequence: str) -> str:
    """Return the next unique short code drawn from *sequence*.

    The returned string is exactly 6 characters long.  DB uniqueness is the
    hard guarantee; the caller's INSERT/UPDATE must be wrapped in a savepoint
    so a rare collision can be retried without aborting the outer transaction.
    """
    seq_val = await session.scalar(select(func.nextval(sequence)))
    prefix = _encode(int(seq_val) % _MAX_SEQ, SEQ_WIDTH)
    suffix = "".join(secrets.choice(ALPHABET) for _ in range(RAND_WIDTH))
    return prefix + suffix
