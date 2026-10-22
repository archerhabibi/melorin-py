FROM python:3.12-slim-bookworm
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
