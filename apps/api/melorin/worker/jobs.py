"""Periodic jobs, one module per domain. This file only re-exports the names the scheduler imports (``arq_app``).

Job bodies live in ``jobs_backup``, ``jobs_panels``, ``jobs_accounts``, ``jobs_identity``, ``jobs_payments`` and ``jobs_reports``;
patch collaborators (``session_factory`` ...) on the module that owns the job.
"""

from melorin.worker.jobs_backup import (
    backup_job,
    panel_backup_job,
)
from melorin.worker.jobs_panels import (
    panel_health_job,
    panel_metrics_job,
    panel_settings_drift_job,
    panel_admin_sync_job,
    panel_event_job,
    panel_event_purge_job,
    bulk_operation_job,
    store_governance_job,
    reconciliation_job,
)
from melorin.worker.jobs_accounts import (
    expiry_job,
    near_expiry_job,
    EXPIRY_LIVE_BATCH,
    NEAR_EXPIRY_MAX_PAGES,
)
from melorin.worker.jobs_identity import (
    identity_auto_link_job,
    reseller_auto_verify_job,
    reseller_identity_recheck_job,
    telegram_login_gc_job,
    privacy_retention_job,
)
from melorin.worker.jobs_payments import (
    bank_sms_reconcile_job,
    receipt_grace_job,
)
from melorin.worker.jobs_reports import (
    daily_report_job,
    store_digest_job,
)

__all__ = [
    "backup_job",
    "panel_backup_job",
    "panel_health_job",
    "panel_metrics_job",
    "panel_settings_drift_job",
    "panel_admin_sync_job",
    "panel_event_job",
    "panel_event_purge_job",
    "bulk_operation_job",
    "store_governance_job",
    "reconciliation_job",
    "expiry_job",
    "near_expiry_job",
    "EXPIRY_LIVE_BATCH",
    "NEAR_EXPIRY_MAX_PAGES",
    "identity_auto_link_job",
    "reseller_auto_verify_job",
    "reseller_identity_recheck_job",
    "telegram_login_gc_job",
    "privacy_retention_job",
    "bank_sms_reconcile_job",
    "receipt_grace_job",
    "daily_report_job",
    "store_digest_job",
]
