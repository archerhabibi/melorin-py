"""Backup jobs: encrypted local backup (+S3) and the per-panel backup.

Both jobs run a shell script under one exit-code protocol (stdout's last line is the artifact path; exit 0 = ok, 3 = local ok but the
off-site copy failed, anything else = failed) and record the outcome as a ``BackupRun``. ``_run_backup_script`` owns that protocol so the
two jobs cannot drift apart.
"""

import asyncio
import logging
import os
import signal
import stat
from dataclasses import dataclass
from pathlib import Path

from melorin.core import integrations
from melorin.core.db import session_factory, utcnow
from melorin.kernel.models.system import BackupRun
from melorin.modules.eventcenter import rules as event_center_rules
from melorin.worker.wrap import tracked_job

log = logging.getLogger("melorin.jobs")

_SCRIPT_TIMEOUT = 900  # seconds; ``lock_ttl`` of both jobs is this plus a margin
_EXIT_OK, _EXIT_OFFSITE_FAILED = 0, 3


def _regular_file_size(location: str) -> int | None:
    """Blocking: size of the artifact, or ``None`` when it is not a readable regular file (size is informational only)."""
    try:
        info = Path(location).stat()
    except (OSError, ValueError):  # missing, permission denied, name too long, embedded NUL ...
        return None
    return info.st_size if stat.S_ISREG(info.st_mode) else None


async def _artifact_size(location: str) -> int | None:
    """Artifact size read off the event loop. Never raises: a successful backup must not turn into a failed run over its metadata."""
    return await asyncio.to_thread(_regular_file_size, location)


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Kill the script and everything it spawned (rclone, gpg ...); the script runs in its own session so the group is ours."""
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()


@dataclass(frozen=True)
class _BackupSpec:
    script: str
    target: str  # ``BackupRun.target``
    label: str  # log wording; unchanged from the pre-refactor messages so log-based alerts keep matching
    ok_note: str
    partial_note: str  # prefix of the details of an exit-3 run (the stderr tail is appended)


_MAIN = _BackupSpec(
    script="backup_secure.sh",
    target="melorin",
    label="backup",
    ok_note="encrypted artifact and checksum verification completed",
    partial_note="local backup OK but S3 upload failed: ",
)
_PANEL = _BackupSpec(
    script="backup_panel.sh",
    target="panel",
    label="panel backup",
    ok_note="panel backup encrypted and verified",
    partial_note="local panel backup OK but S3 upload failed: ",
)


async def _run_backup_script(spec: _BackupSpec) -> str:
    root = Path(os.getenv("MELORIN_PROJECT_ROOT", "/app"))
    started = utcnow()
    status, location, details, size = "failed", None, None, None
    env = dict(os.environ)
    try:
        async with session_factory()() as session:
            s3 = await integrations.get_backup_s3(session)
        if integrations.backup_s3_ready(s3):
            env.update(integrations.rclone_env(s3))
            env["MELORIN_BACKUP_OFFSITE_URI"] = integrations.rclone_uri(s3)
        proc = await asyncio.create_subprocess_exec(
            str(root / "scripts" / spec.script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(root),
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_SCRIPT_TIMEOUT)
        except BaseException:  # timeout, or the job was cancelled: never leave the script running unattended
            await _kill_process_group(proc)
            raise
        lines = stdout.decode(errors="replace").strip().splitlines()
        if proc.returncode in (_EXIT_OK, _EXIT_OFFSITE_FAILED) and lines:
            location = lines[-1]
            size = await _artifact_size(location)
            if proc.returncode == _EXIT_OK:
                status = "succeeded"
                details = spec.ok_note + ("; copied to S3" if env.get("MELORIN_BACKUP_OFFSITE_URI") else "; local only")
            else:  # exit 3: local backup is fine, the off-site copy failed
                status = "partial"
                details = spec.partial_note + stderr.decode(errors="replace")[-1500:]
        else:
            details = stderr.decode(errors="replace")[-2000:]
    except TimeoutError:
        details = f"backup script timed out after {_SCRIPT_TIMEOUT}s and was killed"
    except Exception as exc:
        details = (str(exc) or type(exc).__name__)[:2000]
    async with session_factory()() as session:
        run = BackupRun(status=status, location=location, size=size, details=details, created_at=started, target=spec.target)
        session.add(run)
        await session.flush()  # the run id is the dedup key of its Event Center notice
        await event_center_rules.notify_backup(session, run)
        await session.commit()
    if status != "succeeded":
        log.error("%s %s: %s", spec.label, status, details)
    return status


@tracked_job(lock_ttl=910)
async def backup_job(ctx=None):
    """Always write an encrypted LOCAL backup; also copy it to S3 when enabled in the Admin panel."""
    return await _run_backup_script(_MAIN)


@tracked_job(lock_ttl=910)
async def panel_backup_job(ctx=None):
    """Daily: encrypted backup of the PasarGuard panel (its database and data directory), recorded as ``BackupRun(target="panel")`` (PG-16).

    Does nothing (no run, no alert) until ``MELORIN_PANEL_BACKUP_DATABASE_URL`` and/or ``MELORIN_PANEL_BACKUP_PATHS`` is set: a panel that is
    not backed up by Melorin is "not in use", not "stale". Same exit-code protocol as ``backup_job`` (0 ok, 3 local ok but off-site failed)."""
    if not (os.getenv("MELORIN_PANEL_BACKUP_DATABASE_URL") or os.getenv("MELORIN_PANEL_BACKUP_PATHS")):
        return "not_configured"
    return await _run_backup_script(_PANEL)
