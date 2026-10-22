# Core API image, shared by the `api` and `worker` services (audit W17).
# Three stages, so build and fetch tooling never reaches the image that runs in production:
#   pgdg-key  fetches and dearmors the PostgreSQL apt signing key. Needs curl + gnupg, which stay in this discarded stage.
#   venv      installs the hash-locked runtime requirements (pip --require-hashes) into /opt/venv.
#   runtime   Python + age/rclone/PostgreSQL 16 client (scripts/backup_secure.sh) + the venv + the app.
#             No curl, no gnupg, no pip cache, no test tooling; runs as a non-root user.
# Keep the PostgreSQL client major aligned with the postgres:16 service so custom-format restores work without a
# cross-major compatibility workaround. The base image is pinned by digest by scripts/pin_images.py.
FROM python:3.12-slim-bookworm AS base

FROM base AS pgdg-key
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /out \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /out/apt.postgresql.org.gpg \
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
RUN echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates age rclone postgresql-client-16 \
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
