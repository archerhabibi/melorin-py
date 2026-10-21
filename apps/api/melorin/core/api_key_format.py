"""Wire format of reseller API keys: the prefix and the stored hash. Lives in Core so the channel check needs no feature package."""

import hashlib

PREFIX = "mln_live_"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
