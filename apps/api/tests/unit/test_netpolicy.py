import pytest

from melorin.domain import netpolicy, webhook as wh


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "169.254.169.254",
        "100.100.100.200",
        "100.64.0.1",
        "::1",
        "64:ff9b::7f00:1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::1",
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",
        "192.0.0.8",
        "198.18.0.1",
        "224.0.0.1",
        "0.0.0.0",
        "not-an-ip",
    ],
)
def test_forbidden(ip):
    assert netpolicy.is_forbidden_ip(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_allowed(ip):
    assert not netpolicy.is_forbidden_ip(ip)


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.1", "127.0.0.1"),
        ("0x7f.1", "127.0.0.1"),
        ("2130706433", "127.0.0.1"),
        ("0177.0.0.1", "127.0.0.1"),
        ("example.com", None),
        ("1.2.3.4.5", None),
    ],
)
def test_numeric_host(host, expected):
    got = netpolicy.parse_numeric_host(host)
    assert (str(got) if got else None) == expected


@pytest.mark.parametrize("url", ["https://127.1/", "https://0x7f.1/", "https://2130706433/", "https://100.100.100.200/"])
def test_check_url_rejects_numeric_and_cgnat(url):
    with pytest.raises(wh.WebhookUrlError):
        wh.check_url(url)


def test_check_url_rejects_cgnat_resolution():
    with pytest.raises(wh.WebhookUrlError):
        wh.check_url("https://hook.example.com/", resolved_ips=["100.100.100.200"])
