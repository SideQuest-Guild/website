# syntax=docker/dockerfile:1

# --- Stage 1: build the website (Astro) -------------------------------------------------------
FROM node:24-slim AS website

WORKDIR /src/website
# Absolute URL for canonical/og tags, baked in at build time. Defaults to production (Cabotage builds without build
# args); compose passes its own.
ARG SITE_URL=https://sidequest-guild.com
ENV SITE_URL=${SITE_URL}

COPY website/package.json website/package-lock.json ./
RUN npm ci

COPY website/ ./
RUN npm run build

# --- Stage 2: Python runtime -------------------------------------------------------------------
FROM python:3.15-slim AS runtime

# uv installs/syncs the workspace; copied from the official distroless uv image, not installed via curl|sh.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8000

WORKDIR /app

# Dependency manifests + full source (uv_build needs each package's src/ present to build editable installs,
# so a manifests-only pre-sync layer isn't viable here).
COPY pyproject.toml uv.lock .python-version ./
COPY packages/sidequest-common packages/sidequest-common
COPY api api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --all-packages

# website_dist defaults to <repo-root>/website/dist, resolved from api/src/sidequest_api/lib/website.py
# (parents[4]); keep the same repo-relative layout inside the image so no override is needed.
COPY --from=website /src/website/dist website/dist

# The app only reads /app (bytecode is precompiled; the Cabotage socket lives in /var/run/cabotage), so files stay
# root-owned. A `chown -R /app` here would copy the whole venv into a second ~190 MB layer.
RUN groupadd --system sidequest && useradd --system --gid sidequest --home /app --shell /usr/sbin/nologin sidequest
USER sidequest

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"

CMD ["sidequest-api"]
