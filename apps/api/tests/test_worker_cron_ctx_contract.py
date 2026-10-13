"""ARQ passes a ctx dict as the first positional argument to every cron/function job."""
import inspect

from melorin.worker import jobs
from melorin.worker.arq_app import WorkerSettings


def test_every_worker_function_accepts_arq_ctx():
    for fn in WorkerSettings.functions:
        params = list(inspect.signature(fn).parameters.values())
        assert params, f"{fn.__name__} must accept the ARQ ctx argument"
        assert params[0].kind in (params[0].POSITIONAL_ONLY, params[0].POSITIONAL_OR_KEYWORD), fn.__name__


def test_periodic_jobs_default_ctx_to_none():
    for name in ("backup_job", "panel_health_job", "expiry_job", "near_expiry_job", "reconciliation_job", "privacy_retention_job"):
        assert inspect.signature(getattr(jobs, name)).parameters["ctx"].default is None
