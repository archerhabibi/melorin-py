from pathlib import Path

from _source import read_source


def test_backup_runtime_boundary_is_scheduled_and_audited():
    jobs = read_source(Path(__file__).parents[1].joinpath("melorin", "worker", "jobs.py"))
    arq = read_source(Path(__file__).parents[1].joinpath("melorin", "worker", "arq_app.py"))
    assert "backup_secure.sh" in jobs
    assert "BackupRun" in jobs
    assert "cron(backup_job" in arq
