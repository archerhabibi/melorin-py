from pathlib import Path

from _source import read_source


def test_admin_backup_route_contract_exists():
    source = read_source(Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "router.py"))
    assert '@router.get("/operations/backups"' in source
    assert "BackupRun" in source
