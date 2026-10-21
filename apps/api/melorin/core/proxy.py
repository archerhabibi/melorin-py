"""Trusted reverse-proxy address handling.

Only a socket peer inside the configured trusted networks may influence the
client IP. X-Forwarded-For is walked from right to left so chained proxies do
not let an untrusted hop spoof the address used for rate limits and audit.
"""

from ipaddress import ip_address, ip_network


def _trusted_networks(values: list[str]) -> list:
    networks = []
    for value in values:
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError:
            # A bad optional entry must not disable the remaining safeguards.
            continue
    return networks


def ip_in_networks(address: str | None, configured: list[str]) -> bool:
    """Is ``address`` inside any of the CIDR entries? Fail closed: an unresolvable address ("?", None) is never inside."""
    if not address:
        return False
    try:
        candidate = ip_address(address)
    except ValueError:
        return False
    return any(candidate in network for network in _trusted_networks(configured))


def is_trusted_proxy(address: str | None, configured: list[str]) -> bool:
    return ip_in_networks(address, configured)


def resolve_client_ip(direct: str | None, forwarded: str, configured: list[str]) -> str:
    """Resolve the safest client address from a direct peer and XFF chain."""
    direct = direct or "?"
    if not is_trusted_proxy(direct, configured):
        return direct

    chain = []
    for raw in forwarded.split(","):
        raw = raw.strip()
        try:
            chain.append(str(ip_address(raw)))
        except ValueError:
            continue
    if not chain:
        return direct

    # The first untrusted hop from the proxy side is the client identity.
    for address in reversed(chain):
        if not is_trusted_proxy(address, configured):
            return address
    return chain[0]
