# I37: privacy retention job

ARQ now runs a daily privacy-retention job at 03:00. It removes only expired
and aged `VerificationCode` rows, using the admin-configurable
`privacy.verification_code_retention_days` setting (default: 7 days).

Financial ledger, payment, audit, security, order, and provisioning records
are intentionally preserved. This is the safe baseline for privacy cleanup:
personal data is minimized where it is no longer needed without destroying
accounting or audit evidence.
