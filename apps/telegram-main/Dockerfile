FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
WORKDIR /app
COPY apps/telegram-main/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY apps/telegram-main/runner.py .
COPY apps/telegram-main/tgmain ./tgmain
RUN useradd --create-home --uid 10002 bot && mkdir -p /var/lib/melorin && chown -R bot:bot /app /var/lib/melorin
USER bot
CMD ["python", "runner.py"]
COPY scripts/telegram_healthcheck.py /app/scripts/telegram_healthcheck.py
