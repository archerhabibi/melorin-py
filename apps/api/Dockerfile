# Core API image, shared by the `api` and `worker` services (audit W17).
# Three stages, so build and fetch tooling never reaches the image that runs in production:
#   pgdg-key  fetches and dearmors the PostgreSQL apt signing key. Needs curl + gnupg, which stay in this discarded stage.
#   venv      installs the hash-locked runtime requirements (pip --require-hashes) into /opt/venv.
#   runtime   Python + age/rclone/PostgreSQL 16 client (scripts/backup_secure.sh) + the venv + the app.
#             No curl, no gnupg, no pip cache, no test tooling; runs as a non-root user.
# Keep the PostgreSQL client major aligned with the postgres:16 service so custom-format restores work without a
# cross-major compatibility workaround. The base image is pinned by digest by scripts/pin_images.py.
FROM python:3.15-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9 AS base

FROM base AS pgdg-key
# The key download is the only step here that depends on an external host. CI hit "curl: (56) Recv failure: Connection reset by peer"
# once, so apt and curl both retry (curl needs --retry-all-errors: plain --retry skips connection resets), and the key is saved
# to a file first, then dearmored, so a failed download fails the build at curl instead of being masked by the pipe.
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /out \
    && curl -fsSL --retry 6 --retry-all-errors --retry-delay 5 --connect-timeout 15 --max-time 60 \
        -o /tmp/ACCC4CF8.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && test -s /tmp/ACCC4CF8.asc \
    && gpg --dearmor -o /out/apt.postgresql.org.gpg /tmp/ACCC4CF8.asc \
    && test -s /out/apt.postgresql.org.gpg \
    && chmod 0644 /out/apt.postgresql.org.gpg

FROM base AS venv
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --require-hashes -r /tmp/requirements.txt

FROM base AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY --from=pgdg-key /out/apt.postgresql.org.gpg /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg
# PG-16: Melorin's own database is PostgreSQL 16, the PasarGuard panel (TimescaleDB) is 17. pg_dump refuses a server NEWER than itself,
# so both clients are installed; pg_wrapper then runs the newest one, which can dump either server.
RUN echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates age rclone postgresql-client-16 postgresql-client-17 tesseract-ocr tesseract-ocr-fas tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY --from=venv /opt/venv /opt/venv
RUN useradd --create-home --uid 10001 appuser
COPY apps/api/melorin ./melorin
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini apps/api/pyproject.toml ./
COPY scripts ./scripts
RUN mkdir -p /app/var/storage && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "melorin.app:app", "--host", "0.0.0.0", "--port", "8000"]
