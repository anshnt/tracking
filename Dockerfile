# syntax=docker/dockerfile:1
# Portal image: API + worker (same image, different command) + built web UI.
# Build from the repo root:  docker build -t tracking-portal:lab .
# Tags mirror infra/versions.env; digests are TODO (infra/digests.txt). Override with --build-arg.
ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.13-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.18

# ---- web UI -> apps/web/dist ------------------------------------------------------------
FROM ${NODE_IMAGE} AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

# ---- python deps ------------------------------------------------------------------------
FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS api-build
COPY --from=uv /uv /usr/local/bin/uv
# Same path as the runtime stage: the venv is not relocatable and the editable install
# keeps portal/main.py at /app/apps/api/portal, which is how it finds apps/web/dist.
WORKDIR /app/apps/api
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/portal ./portal
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./
RUN uv sync --frozen --no-dev

# ---- runtime ----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 portal \
 && useradd --system --uid 10001 --gid portal --no-create-home --shell /usr/sbin/nologin portal
WORKDIR /app/apps/api
COPY --from=api-build --chown=portal:portal /app/apps/api /app/apps/api
COPY --from=web --chown=portal:portal /src/apps/web/dist /app/apps/web/dist
ENV PATH="/app/apps/api/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER portal
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"]
# Worker: override the command with  python -m portal.worker
# Migrations: override with  alembic upgrade head  (needs DATABASE_URL)
CMD ["uvicorn", "portal.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
