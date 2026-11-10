"""Panel events have ONE way in and ONE consumer (audit T07): this pins the design so a second path cannot appear by accident."""

from __future__ import annotations

import inspect

from melorin.modules.vpn import panel_events, webhook_router
from melorin.worker import jobs


def test_the_worker_job_only_consumes_stored_events_and_never_asks_the_panel():
    src = inspect.getsource(jobs.panel_event_job)
    code = src.split('"""')[2]  # the body after the docstring
    assert "panel_events.run_pending(" in code
    assert "build_adapter" not in code and "list_accounts" not in code and "get_account" not in code


def test_the_webhook_stores_through_ingest_and_processes_through_the_same_run_pending():
    src = inspect.getsource(webhook_router)
    assert "panel_events.ingest(" in src and "panel_events.run_pending(" in src


def test_ingest_has_no_panel_call_and_events_are_deduplicated_by_key():
    src = inspect.getsource(panel_events.ingest)
    assert "build_adapter" not in src and "get_account" not in src
    assert "dedup_key" in src
