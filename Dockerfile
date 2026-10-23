# syntax=docker/dockerfile:1
# Multi-stage image shared by API, dashboard and worker (different commands).
FROM python:3.12-slim AS build
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels ".[dashboard]"

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    IMPACTLENS_DB_PATH=/app/data/impactlens.db IMPACTLENS_CACHE_DIR=/app/cache \
    IMPACTLENS_SAMPLES_DIR=/app/samples MARKET_DATA_CSV_DIR=/app/samples/prices
WORKDIR /app
COPY --from=build /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels impactlens streamlit && rm -rf /wheels \
    && useradd --create-home --uid 10001 impactlens \
    && mkdir -p /app/data /app/cache /app/backups && chown -R impactlens:impactlens /app
# Synthetic demo reference data only (no private portfolios, no secrets).
COPY --chown=impactlens:impactlens data/samples /app/samples
COPY --chown=impactlens:impactlens src/impactlens/dashboard/app.py /app/dashboard_app.py
USER impactlens
EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "impactlens.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
