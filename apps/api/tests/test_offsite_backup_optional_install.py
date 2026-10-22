from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[3]


def test_installer_does_not_gate_on_offsite_backup():
    script = (ROOT / "scripts/install_server.sh").read_text()
    assert "BACKUP_OFFSITE_URI is required" not in script
    assert "S3 / SMTP are optional" in script
    assert "Admin -> Settings -> Integrations" in script


def test_production_config_keeps_local_backup_requirement_only():
    config = read_source(ROOT / "apps/api/melorin/core/config.py")
    assert "MELORIN_BACKUP_RECIPIENT_FILE is required outside development" in config
    assert "MELORIN_BACKUP_OFFSITE_URI is required outside development" not in config
