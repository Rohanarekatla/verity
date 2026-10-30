# A17.1 — the Verity readiness-scan image.
#
# One image carrying both toolchains a scan needs — Python (orchestrator,
# agents, CLI) and Node (the Chromium render/axe worker) — plus the Chromium
# build matching the worker's Playwright, so a readiness scan runs the same in
# CI, in a cron job, or on a laptop. No browser download happens at run time.
#
# Build:  docker build -f deploy/Dockerfile -t verity:local .
# Run:    docker run --rm verity:local scan https://example.com
#         docker run --rm verity:local webmcp /app/data/fixtures/contrast-fail.html
#         docker run --rm -v "$PWD/out:/out" verity:local \
#                    scan https://example.com --sarif /out/verity.sarif
#
# The base is plain python-slim (not a pinned Playwright image) so Chromium is
# installed to match whatever Playwright version the node worker's lockfile
# resolves — the two can never drift apart.

FROM python:3.13-slim

# Node 22 for the render/axe worker (matches .github/workflows/ci.yml).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv is the project's toolchain; the actual deps are pinned by uv.lock.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Python deps first (layer-cached): copy only the lockfiles.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Node worker deps, then the Chromium that matches its Playwright, then build.
COPY node-worker/package.json node-worker/package-lock.json ./node-worker/
RUN cd node-worker && npm ci
RUN cd node-worker && npx playwright install --with-deps chromium
COPY node-worker ./node-worker
RUN cd node-worker && npm run build

# The rest of the source, then install the project itself.
COPY . .
RUN uv sync --frozen

ENV PYTHONUNBUFFERED=1

# The CLI is the entrypoint; args are verity subcommands (scan, agent-check,
# webmcp, mcp). A bare `docker run` prints help.
ENTRYPOINT ["uv", "run", "python", "-m", "verity.cli"]
CMD ["--help"]
