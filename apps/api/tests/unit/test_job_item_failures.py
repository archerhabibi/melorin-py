"""T-W06 / T-R15: errors a job isolates per item must be countable, not silent."""

from __future__ import annotations

import inspect
import re

from melorin.core import metrics
from melorin.worker import jobs
from melorin.worker.wrap import item_failed


def test_item_failed_counts_per_job():
    metrics.reset()
    item_failed("reconciliation_job")
    item_failed("reconciliation_job")
    item_failed("panel_health_job")
    rendered = metrics.render()
    assert 'melorin_job_item_failures_total{job="reconciliation_job"} 2' in rendered
    assert 'melorin_job_item_failures_total{job="panel_health_job"} 1' in rendered


def test_every_isolating_except_in_jobs_reports_the_failure():
    """A ``except Exception`` that only logs and continues must also call ``item_failed`` with a real job name."""
    src = inspect.getsource(jobs)
    job_names = set(re.findall(r"^async def (\w+_job)\(", src, flags=re.M))
    labels = set(re.findall(r'item_failed\("(\w+)"\)', src))
    assert labels, "no item_failed call sites found"
    assert labels <= job_names, f"unknown job label(s): {labels - job_names}"
    # every `except Exception:` block that swallows (logs a warning, no `raise`) is followed by item_failed within 4 lines
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "except Exception:" or line.strip().startswith("except Exception:  #"):
            window = "\n".join(lines[i : i + 5])
            if "log.warning" in window and "raise" not in window:
                assert "item_failed(" in window, f"swallowed error without item_failed near jobs.py line {i + 1}"
