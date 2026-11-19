"""One outbound-address policy for every server-side request to a user-influenced host (audit V-011).

Pure (no I/O): callers resolve names themselves and pass the addresses in. An address is allowed only when it is globally routable
AND not in one of the ranges ``ipaddress`` still reports as global (CGNAT, NAT64, 6to4, Teredo, IPv4-mapped/compatible forms are
unwrapped and judged by the IPv4 address they carry).
"""

import ipaddress

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_EXTRA_FORBIDDEN = tuple(
    ipaddress.ip_network(n)
    for n in (
        "100.64.0.0/10",  # CGNAT / shared address space: Tailscale, Alibaba metadata 100.100.100.200
        "192.0.0.0/24",  # IETF protocol assignments
        "198.18.0.0/15",  # benchmarking
        "192.88.99.0/24",  # deprecated 6to4 relay anycast
        "64:ff9b::/96",  # NAT64 well-known prefix
        "64:ff9b:1::/48",  # local-use NAT64
        "2002::/16",  # 6to4
        "2001::/32",  # Teredo
        "100::/64",  # discard-only
    )
)


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    packed = ip.packed
    if packed[:12] == b"\x00" * 12:  # IPv4-compatible (::a.b.c.d), deprecated
        return ipaddress.IPv4Address(packed[12:])
    if ip in ipaddress.ip_network("64:ff9b::/96"):
        return ipaddress.IPv4Address(packed[12:])
    if ip in ipaddress.ip_network("2002::/16"):
        return ipaddress.IPv4Address(packed[2:6])
    return None


def is_forbidden_ip(ip: IPAddress | str) -> bool:
    """True when a server-side request must not go to this address."""
    if isinstance(ip, str):
        try:
            ip = ipaddress.ip_address(ip.strip("[]"))
        except ValueError:
            return True  # not an address at all: refuse
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_v4(ip)
        if inner is not None and is_forbidden_ip(inner):
            return True
    if not ip.is_global or ip.is_multicast:
        return True
    return any(ip in net for net in _EXTRA_FORBIDDEN if net.version == ip.version)


def parse_numeric_host(host: str) -> IPAddress | None:
    """Parse the legacy numeric IPv4 spellings a URL parser leaves alone (``127.1``, ``0x7f.1``, ``2130706433``, ``0177.0.0.1``).

    Returns the address, or None when ``host`` is an ordinary name. A real IP literal is returned as well.
    """
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or not all(parts):
        return None
    nums: list[int] = []
    for part in parts:
        try:
            if part.lower().startswith("0x"):
                nums.append(int(part, 16))
            elif len(part) > 1 and part.startswith("0") and part.isdigit():
                nums.append(int(part, 8))
            elif part.isdigit():
                nums.append(int(part, 10))
            else:
                return None
        except ValueError:
            return None
    *head, last = nums
    if any(n > 255 for n in head) or last >= 256 ** (4 - len(head)):
        return None
    value = last
    for i, n in enumerate(head):
        value += n << (8 * (3 - i))
    return ipaddress.IPv4Address(value)
