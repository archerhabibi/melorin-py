"""Job collaborators live in one module per domain (``melorin.worker.jobs_*``); patch them through here."""

from melorin.worker import jobs_accounts, jobs_backup, jobs_identity, jobs_panels, jobs_payments, jobs_reports

JOB_MODULES = (jobs_accounts, jobs_backup, jobs_identity, jobs_panels, jobs_payments, jobs_reports)


def patch_jobs(monkeypatch, name, value):
    """Replace ``name`` in every job module that uses it (e.g. ``session_factory``)."""
    hit = False
    for mod in JOB_MODULES:
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, value)
            hit = True
    assert hit, f"no job module has {name}"


def jobs_source() -> str:
    """Source of every job module together (the contract tests assert on the whole job set)."""
    import inspect

    return "".join(inspect.getsource(m) for m in JOB_MODULES)
