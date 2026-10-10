FROM python:3.12-slim
WORKDIR /app
COPY apps/telegram-main/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/telegram-main/runner.py .
RUN useradd --create-home --uid 10002 bot && mkdir -p /var/lib/melorin && chown -R bot:bot /app /var/lib/melorin
USER bot
CMD ["python", "runner.py"]
