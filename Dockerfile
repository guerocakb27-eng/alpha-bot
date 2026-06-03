# ─── Stage 1: build dashboard ──────────────────────────────────────
FROM node:20-alpine AS dashboard-build
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY dashboard/ .
RUN npm run build

# ─── Stage 2: runtime ──────────────────────────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY config.py main.py alembic.ini ./
COPY core/ ./core/
COPY indicators/ ./indicators/
COPY backtesting/ ./backtesting/
COPY strategies/ ./strategies/
COPY database/ ./database/
COPY alembic/ ./alembic/
COPY api/ ./api/
COPY scripts/ ./scripts/

# Built dashboard from stage 1
COPY --from=dashboard-build /app/dashboard/dist ./dashboard/dist

RUN mkdir -p /app/logs /app/reports

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
