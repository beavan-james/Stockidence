# Backend image: FastAPI + Dagster (webserver/daemon run via overridden commands).
# Python 3.12 to match local dev (.python-version). libgomp1 is for xgboost.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install the package (deps from pyproject.toml, incl. the ML stack used by
# the quarterly retrain) before copying source for a stable layer cache.
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv pip install --system .

# Repo files the pipeline reads at runtime: Dagster workspace + notebook,
# scripts and artifacts for the quarterly job. Model/datasets/ is excluded
# (rebuilt by the job); data/ arrives as a volume; .env is NEVER baked in.
COPY workspace.yaml dagster.yaml ./
COPY Model/ Model/

# ipykernel spec for the retrain op's dedicated "stockidence" kernel is
# provisioned at runtime by the op itself; nothing to do at build time.

EXPOSE 8000 3000

# Default: the API. Compose overrides command for dagster-webserver/daemon.
# Single worker: the refresh cooldown + DuckDB single-writer assume one process.
CMD ["uvicorn", "stockidence.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
