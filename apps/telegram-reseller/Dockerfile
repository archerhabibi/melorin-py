FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
WORKDIR /app
COPY apps/telegram-reseller/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY apps/telegram-reseller/runner.py .
COPY apps/telegram-reseller/tgreseller ./tgreseller
COPY apps/telegram-main/tgmain ./tgmain
RUN useradd --create-home --uid 10003 bot && mkdir -p /var/lib/melorin && chown -R bot:bot /app /var/lib/melorin
USER bot
CMD ["python", "runner.py"]
COPY scripts/telegram_healthcheck.py /app/scripts/telegram_healthcheck.py
