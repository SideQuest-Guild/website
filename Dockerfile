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

# --- Stage 2: build wowsims/forever's sim CLI and data -----------------------------------------
FROM golang:1.27-bookworm AS wowsims

# libprotobuf-dev ships google/protobuf/descriptor.proto, which common.proto imports; protobuf-compiler alone doesn't.
RUN apt-get update && apt-get install -y --no-install-recommends git protobuf-compiler libprotobuf-dev \
    && rm -rf /var/lib/apt/lists/*

# Pinned so a game-data change upstream can't silently change sim results; bump deliberately after checking
# `siml fmt -check ui/specs` and a known build still passes (mirrors the wow-forever-sim skill's `setup`).
ARG WOWSIMS_COMMIT=d0ab8659ea
WORKDIR /src
RUN git clone https://github.com/wowsims/forever . \
    && git checkout ${WOWSIMS_COMMIT}
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
ENV PATH="/root/go/bin:${PATH}"
RUN make sim/core/proto/api.pb.go
RUN go build -buildvcs=false --tags=with_db -o bin/wowsimcli ./cmd/wowsimcli

# The runtime image only needs the binary, the SIML name tables, the item database, and the spec presets. Specs
# without a defaults.siml keep their rotation in *.apl.json and their talents in presets.ts, which the engine reads.
RUN mkdir -p /opt/wowsims/bin /opt/wowsims/sim/siml /opt/wowsims/assets/database \
    && cp bin/wowsimcli /opt/wowsims/bin/wowsimcli \
    && cp sim/siml/names.json /opt/wowsims/sim/siml/names.json \
    && cp assets/database/db.json /opt/wowsims/assets/database/db.json \
    && find ui/specs \( -name '*.siml' -o -name '*.apl.json' -o -name 'presets.ts' \) \
        -exec install -D {} /opt/wowsims/{} \;

# --- Stage 3: Python runtime -------------------------------------------------------------------
FROM python:3.15-slim AS runtime

# uv installs/syncs the workspace; copied from the official distroless uv image, not installed via curl|sh.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    WOWSIMS_DIR=/opt/wowsims

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
COPY --from=wowsims /opt/wowsims /opt/wowsims

# The app only reads /app (bytecode is precompiled; the Cabotage socket lives in /var/run/cabotage), so files stay
# root-owned. A `chown -R /app` here would copy the whole venv into a second ~190 MB layer.
RUN groupadd --system sidequest && useradd --system --gid sidequest --home /app --shell /usr/sbin/nologin sidequest
USER sidequest

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"

CMD ["sidequest-api"]
