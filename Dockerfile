FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    QUOTE_DATABASE_PATH=/app/data/quotes.sqlite3

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY src/ ./src/
RUN mkdir -p /app/data && chown -R app:app /app

USER app

# One-shot cloud task. Invoke from a managed scheduler; do not treat this
# process as a permanent service or schedule it from GitHub Actions.
CMD ["python", "-m", "arbitrage_monitor.cloud_worker"]
