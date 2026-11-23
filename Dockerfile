# Backend image: FastAPI + Dagster (webserver/daemon run via overridden commands).
# Python 3.12 to match local dev (.python-version). libgomp1 is for xgboost.
FROM python:3.12-slim

# STOCKIDENCE_ROOT: the package installs into site-packages, so it can't
# find Model/ (quarterly job) relative to its own files.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    STOCKIDENCE_ROOT=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Qwen3.5-4B's tokenizer (12.8 MB), for counting prompt tokens before each
# call to the local model: Ollama has no endpoint for it. Pinned to a commit
# of the model's Hugging Face repo, so the file never changes under us.
ADD https://huggingface.co/Qwen/Qwen3.5-4B/resolve/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/tokenizer.json \
    tokenizers/qwen3.5-4b-tokenizer.json

# Install the package (deps from pyproject.toml, incl. the ML stack used by
# the quarterly retrain) before copying source for a stable layer cache.
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv pip install --system .

# Repo files the pipeline reads at runtime: Dagster workspace + notebook,
# scripts and artifacts for the quarterly job. Model/datasets/ is excluded
# (rebuilt by the job); data/ arrives as a volume; .env is NEVER baked in.
COPY workspace.yaml workspace.docker.yaml dagster.yaml ./
COPY Model/ Model/

# ipykernel spec for the retrain op's dedicated "stockidence" kernel is
# provisioned at runtime by the op itself; nothing to do at build time.

EXPOSE 8000 3000

# Default: the API. Compose overrides command for dagster-webserver/daemon.
# Single worker: the refresh cooldown + DuckDB single-writer assume one process.
CMD ["uvicorn", "stockidence.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
