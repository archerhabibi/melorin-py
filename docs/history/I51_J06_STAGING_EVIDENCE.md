# I51: J06 Staging Evidence Gate

J06 cannot be honestly fixed by claiming that local static checks prove Docker,
Telegram, payment gateways, real VPN panels, Prometheus, or scheduled backup
behavior. The project now has one fail-closed staging command:
`scripts/j06_staging_evidence.sh`.

The Compose stack now health-checks API, worker, both web apps, Caddy,
Prometheus, and both Telegram runners. The integration gate can additionally
probe Telegram `getMe`, a real panel endpoint, Prometheus readiness, and the
encrypted backup/restore drill when the corresponding staging variables and
credentials are supplied.

The command writes timestamped metadata, service status, logs, integration
results, and optional restore results. Missing credentials fail the run rather
than producing fake evidence. The release matrix remains blocked until a
real staging operator reviews that bundle and updates only the evidence rows
actually demonstrated.
