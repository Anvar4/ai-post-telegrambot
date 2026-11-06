FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Tashkent \
    DATA_DIR=/app/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Faqat tanlangan provayderlar: EXTRAS=anthropic | gemini | all | "" (faqat OpenAI)
ARG EXTRAS=all
COPY pyproject.toml README.md ./
COPY app ./app
RUN if [ -n "$EXTRAS" ]; then pip install ".[${EXTRAS}]"; else pip install .; fi

COPY alembic ./alembic
COPY alembic.ini ./
COPY assets ./assets
COPY scripts ./scripts

RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /app/data \
    && chown -R bot:bot /app
USER bot

# Heartbeat 10 daqiqa yangilanmasa — bot jarayoni to'xtatiladi, compose uni qayta ishga tushiradi
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
    CMD python -m app.healthcheck

CMD ["python", "-m", "app"]
