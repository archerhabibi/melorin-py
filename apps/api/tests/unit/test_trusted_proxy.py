from melorin.core.proxy import is_trusted_proxy, resolve_client_ip


def test_cidr_trusted_proxy_uses_forwarded_client():
    assert is_trusted_proxy("172.28.4.12", ["172.28.0.0/16"])
    assert resolve_client_ip("172.28.4.12", "203.0.113.8", ["172.28.0.0/16"]) == "203.0.113.8"


def test_untrusted_peer_cannot_spoof_forwarded_header():
    assert resolve_client_ip("198.51.100.9", "203.0.113.8", ["172.28.0.0/16"]) == "198.51.100.9"


def test_chained_proxy_uses_first_untrusted_hop_from_right():
    configured = ["172.28.0.0/16"]
    assert resolve_client_ip("172.28.1.2", "198.51.100.7, 172.28.2.3", configured) == "198.51.100.7"


def test_invalid_network_entry_does_not_disable_valid_entries():
    assert is_trusted_proxy("127.0.0.1", ["not-a-network", "127.0.0.1"])
    assert resolve_client_ip("127.0.0.1", "not-an-ip, 203.0.113.4", ["not-a-network", "127.0.0.1"]) == "203.0.113.4"
