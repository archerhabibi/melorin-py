"""V-024: static guard for the Compose hardening baseline (no Docker daemon needed)."""

import ipaddress
import json
import re
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parents[4]
COMPOSE = yaml.safe_load((PROJECT / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]
# Long-running services that must drop every capability and refuse privilege gain.
HARDENED = ["postgres", "redis", "store_web", "admin_web", "api", "worker", "backup", "telegram_main", "telegram_reseller"]


def test_long_running_services_drop_all_capabilities_and_block_new_privileges():
    for name in HARDENED:
        svc = SERVICES[name]
        assert svc.get("cap_drop") == ["ALL"], name
        assert "no-new-privileges:true" in svc.get("security_opt", []), name


def test_only_the_documented_capabilities_are_added_back():
    allowed = {
        "postgres": {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"},
        "redis": {"CHOWN", "SETGID", "SETUID"},
        "store_web": {"CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID", "NET_BIND_SERVICE"},
        "admin_web": {"CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID", "NET_BIND_SERVICE"},
    }
    for name in HARDENED:
        assert set(SERVICES[name].get("cap_add", [])) == allowed.get(name, set()), name


def test_web_containers_run_with_a_read_only_root_and_tmpfs_for_nginx_state():
    for name in ("store_web", "admin_web"):
        svc = SERVICES[name]
        assert svc["read_only"] is True
        assert any(t.startswith("/var/cache/nginx") for t in svc["tmpfs"])


def test_subnet_is_configurable_and_default_is_trusted_by_default():
    subnet = COMPOSE["networks"]["backend"]["ipam"]["config"][0]["subnet"]
    assert subnet == "${MELORIN_SUBNET:-172.28.0.0/16}"
    env = (PROJECT / ".env.example").read_text()
    default = re.search(r"(?m)^MELORIN_SUBNET=(\S+)$", env).group(1)
    trusted = json.loads(re.search(r"(?m)^MELORIN_TRUSTED_PROXY_IPS=(.+)$", env).group(1))
    net = ipaddress.ip_network(default)
    assert any((n := ipaddress.ip_network(t, strict=False)).version == net.version and n.supernet_of(net) for t in trusted)


def test_weekly_image_scan_workflow_exists():
    assert "trivy" in (PROJECT / ".github/workflows/image-scan.yml").read_text().lower()
