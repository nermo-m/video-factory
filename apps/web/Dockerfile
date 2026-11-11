# syntax=docker/dockerfile:1
# Build from the repository root: docker build -f apps/web/Dockerfile .

FROM node:22-bookworm-slim AS build
ENV PNPM_HOME=/pnpm \
    PATH="/pnpm:$PATH" \
    NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter "web..."
COPY apps/web apps/web
RUN pnpm --filter web build

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
# The standalone output mirrors the repository layout, so the server is at apps/web/server.js.
COPY --from=build --chown=node:node /repo/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /repo/apps/web/.next/static ./apps/web/.next/static
USER node
EXPOSE 3000
# 0.0.0.0 is inside the container only. The host side binds 127.0.0.1 in docker-compose.yml.
CMD ["node", "apps/web/server.js"]
