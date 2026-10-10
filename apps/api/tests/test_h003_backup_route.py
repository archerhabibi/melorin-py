from pathlib import Path


def test_admin_backup_route_contract_exists():
    source = Path(__file__).parents[1].joinpath("melorin", "modules", "admin", "router.py").read_text()
    assert '@router.get("/operations/backups"' in source
    assert "BackupRun" in source
