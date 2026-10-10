from dataclasses import dataclass


@dataclass(frozen=True)
class ServerCandidate:
    id: object
    healthy: bool
    enabled: bool
    capacity: int
    active_accounts: int
    product_codes: tuple[str, ...] | None  # None = compatible with all
    panel_kind: str


def select_server(cands: list[ServerCandidate], product_code: str) -> ServerCandidate | None:
    """V1 rule: compatible + enabled + healthy + has capacity, then fewest active accounts."""
    ok = [
        c
        for c in cands
        if c.enabled
        and c.healthy
        and c.active_accounts < c.capacity
        and (c.product_codes is None or product_code in c.product_codes)
    ]
    if not ok:
        return None
    return min(ok, key=lambda c: (c.active_accounts, str(c.id)))
