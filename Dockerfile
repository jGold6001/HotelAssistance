# syntax=docker/dockerfile:1.7
#
# Hotel Assistance: FastAPI backend + static chat frontend in one image.
#
# Two stages so the runtime image carries no uv binary, no build cache, no
# lock-file resolution. Dependencies are installed from uv.lock exactly as
# pinned (`--frozen`), without the dev group.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- builder --
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer: only the manifest and lock file, so source edits do not
# invalidate it. The project itself is not installed - it runs from the
# source tree via PYTHONPATH, which keeps the frontend and mock-database
# paths (resolved relative to the package) working unchanged.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------- runtime --
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src/backend

# Unprivileged user; UID 1000 matches the default first user on most Linux
# hosts, so bind-mounted .cache/ and output/ stay writable.
ARG APP_UID=1000
RUN groupadd --gid ${APP_UID} app \
    && useradd --uid ${APP_UID} --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src/ /app/src/

# Writable state: embedding cache and chat transcripts. Both are mounted from
# the host by docker-compose; created here so the image also runs standalone.
RUN mkdir -p /app/.cache /app/output && chown -R app:app /app/.cache /app/output

USER app

EXPOSE 8000

# curl is not in the slim image; the health probe uses the stdlib instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "hotel_assistance.main:app", "--host", "0.0.0.0", "--port", "8000"]
