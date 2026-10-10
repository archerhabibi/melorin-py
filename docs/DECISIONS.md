# Melorin ADR / open decisions

## Decided in V1
- Modular monolith; only Core owns PostgreSQL and business rules.
- PostgreSQL ledger is append-only source of truth; balance is a locked projection.
- Internal transactional outbox, polling worker in V1; broker remains replaceable.
- Sanaei and PasarGuard adapters implement one standard interface.
- Manual card receipt flow ships; online gateway adapter is optional and disabled until configured.
- Admin can manually review/retry/attach/refund; provisioning failure never auto-refunds.
- Iranian Rial is default currency, amounts are integers in smallest canonical unit.

## Must be approved before production
- Exact email authentication provider/SMTP and Google OAuth production settings.
- Final debt-limit boundary, reseller wallet funding/adjustment policy, commission debt policy.
- Referral attribution scope (platform vs store).
- JWT/session policy, Celery/ARQ choice, Caddy/Nginx, Sentry and metrics stack.
- S3-compatible storage, RPO/RTO, backup target and restore-test schedule.
- Telegram Event Center group/topic permissions and bot token ownership.
- Admin account bootstrap and mandatory/optional 2FA policy.

Open decisions are runtime-configurable where safe, but are not silently treated as requirements.
