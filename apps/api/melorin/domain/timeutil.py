"""One place for UTC time helpers (audit T01).

SQLite hands back naive datetimes while PostgreSQL returns aware ones; every comparison must therefore go through
``aware``. The module lives in ``domain`` because ``domain`` imports nothing of ours and every other layer may import it.
"""

import datetime as dt
from typing import overload


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@overload
def aware(value: dt.datetime) -> dt.datetime: ...
@overload
def aware(value: None) -> None: ...
def aware(value: dt.datetime | None) -> dt.datetime | None:
    """Treat a naive datetime as UTC; ``None`` stays ``None``."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
