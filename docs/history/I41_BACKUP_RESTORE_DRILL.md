# I41: backup and restore drill

Added `scripts/backup_restore_drill.sh`, which decrypts and checksum-verifies a
backup, restores it into a uniquely named temporary PostgreSQL database, checks
that public tables exist, and removes that temporary database on exit.

Run it with:

```bash
BACKUP_ARCHIVE=... \
BACKUP_IDENTITY_FILE=... \
MELORIN_DATABASE_URL=postgresql://user:password@host:5432/melorin \
MELORIN_RPO_HOURS=24 \
MELORIN_RTO_HOURS=8 \
make restore-drill
```

The repository now has an executable acceptance path for the documented RPO
of 24 hours and RTO of 8 hours. A passing static check is not runtime evidence:
the drill must run against a real encrypted backup and PostgreSQL target in
CI/staging, with its timestamp and duration attached to the release matrix.
