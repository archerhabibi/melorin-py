FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/api/melorin ./melorin
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini apps/api/pyproject.toml ./
COPY scripts ./scripts
RUN mkdir -p /app/var/storage && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "melorin.app:app", "--host", "0.0.0.0", "--port", "8000"]
