# Backup Implementation

Backup source is implemented by `scripts/backup_secure.sh`. It uses `PGPASSFILE`, age recipient encryption, SHA-256 verification, retention cleanup, and optional rclone off-host copy. Restore evidence is checked by `scripts/backup_restore_verify.sh`, which verifies the checksum, decrypts the archive, and runs `pg_restore --list`.

These scripts are integration boundaries, not proof of a completed production restore. A release still requires PostgreSQL, age, off-host storage, and a real restore drill.
