# A17.1 — the Verity readiness-scan image.
#
# One image that carries both toolchains Verity needs — Python (orchestrator,
# agents, CLI) and Node (the Chromium render/axe worker) — plus the Chromium
# build, so a readiness scan over a site list runs the same in CI, in a cron
# job, or on a laptop. Pinned by digest/version where it matters; the browser
# is baked in so no download happens at run time (the Action caches it between
# runs, but the image needs it present).
#
# Build:  docker build -f deploy/Dockerfile -t verity:local .
# Run:    docker run --rm verity:local scan https://example.com
#         docker run --rm -v "$PWD/report:/out" verity:local \
#                    scan https://example.com --sarif /out/verity.sarif

# Playwright's Python image carries a matching Chromium + its OS deps already,
# which is the fiddly part to get right by hand.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Node 22+ for the worker (the base image ships Node, but pin the major).
RUN node --version | grep -Eq '^v(2[2-9]|[3-9][0-9])' \
    || (echo "need Node >= 22" >&2 && exit 1)

WORKDIR /app

# Python deps first (layer-cached): uv is the project's toolchain.
RUN pip install --no-cache-dir uv==0.5.11
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project 2>/dev/null || uv sync --no-install-project

# Node worker deps + build.
COPY node-worker/package.json node-worker/package-lock.json ./node-worker/
RUN cd node-worker && npm ci
COPY node-worker ./node-worker
RUN cd node-worker && npm run build

# The rest of the source.
COPY . .
RUN uv sync --frozen 2>/dev/null || uv sync

# A readiness scan should never need a browser download at run time.
ENV PLAYWRIGHT_BROWSERS_PATH=0
ENV PYTHONUNBUFFERED=1

# The CLI is the entrypoint; args are verity subcommands (scan, agent-check,
# webmcp, mcp). Default to --help so a bare `docker run` is self-documenting.
ENTRYPOINT ["uv", "run", "python", "-m", "verity.cli"]
CMD ["--help"]
