from pathlib import Path

from _source import read_source


def test_backup_runtime_boundary_is_scheduled_and_audited():
    jobs = read_source(Path(__file__).parents[2].joinpath("melorin", "worker", "jobs.py"))
    arq = read_source(Path(__file__).parents[2].joinpath("melorin", "worker", "arq_app.py"))
    assert "backup_secure.sh" in jobs
    assert "BackupRun" in jobs
    assert "backup_job" not in arq and "panel_backup_job" not in arq  # T-R14: the Worker no longer runs backups
    scheduler = read_source(Path(__file__).parents[2].joinpath("melorin", "worker", "backup_main.py"))
    assert "jobs.backup_job" in scheduler and "jobs.panel_backup_job" in scheduler
