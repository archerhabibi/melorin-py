from pathlib import Path


def test_backup_runtime_boundary_is_scheduled_and_audited():
    jobs = Path(__file__).parents[1].joinpath("melorin", "worker", "jobs.py").read_text()
    arq = Path(__file__).parents[1].joinpath("melorin", "worker", "arq_app.py").read_text()
    assert "backup_secure.sh" in jobs
    assert "BackupRun" in jobs
    assert "cron(backup_job" in arq
