FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
WORKDIR /app
# Backup tooling used by scripts/backup_secure.sh (worker). Keep the client
# major aligned with the postgres:16 service to make custom-format restores
# work without a cross-major compatibility workaround.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg age rclone \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 appuser
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY apps/api/melorin ./melorin
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini apps/api/pyproject.toml ./
COPY scripts ./scripts
RUN mkdir -p /app/var/storage && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "melorin.app:app", "--host", "0.0.0.0", "--port", "8000"]
