# syntax=docker/dockerfile:1
# Browser test runner. Build from the repository root (see docker-compose.e2e.yml).
# The image tag must match the @playwright/test version in apps/web/package.json.
FROM mcr.microsoft.com/playwright:v1.65.0-noble

ENV PNPM_HOME=/pnpm \
    PATH="/pnpm:$PATH" \
    CI=1
# This image's Node has no corepack. The version matches "packageManager" in package.json.
RUN npm install --global pnpm@10.20.0
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter "web..."
COPY apps/web/playwright.config.ts apps/web/tsconfig.json apps/web/
COPY apps/web/e2e apps/web/e2e
WORKDIR /repo/apps/web
ENTRYPOINT ["pnpm", "exec", "playwright", "test"]
