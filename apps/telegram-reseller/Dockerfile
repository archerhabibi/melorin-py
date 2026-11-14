FROM python:3.15-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9
WORKDIR /app
COPY apps/telegram-reseller/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY apps/telegram-reseller/runner.py .
COPY apps/telegram-reseller/tgreseller ./tgreseller
COPY apps/telegram-main/runner.py /app/telegram-main/runner.py
COPY apps/telegram-main/tgmain /app/telegram-main/tgmain
RUN useradd --create-home --uid 10003 bot && mkdir -p /var/lib/melorin && chown -R bot:bot /app /var/lib/melorin
USER bot
CMD ["python", "runner.py"]
COPY scripts/telegram_healthcheck.py /app/scripts/telegram_healthcheck.py
