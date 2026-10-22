FROM python:3.12-slim
WORKDIR /app
COPY apps/telegram-main/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY apps/telegram-main/runner.py .
COPY apps/telegram-main/tgmain ./tgmain
RUN useradd --create-home --uid 10002 bot && mkdir -p /var/lib/melorin && chown -R bot:bot /app /var/lib/melorin
USER bot
CMD ["python", "runner.py"]
COPY scripts/telegram_healthcheck.py /app/scripts/telegram_healthcheck.py
