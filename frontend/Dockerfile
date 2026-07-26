# syntax=docker/dockerfile:1.6
# LifeTree frontend image — Next.js standalone build.
# Uses Node 22 (required by Next.js 16).

# ---------- Stage 1: deps ----------
FROM node:22-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# ---------- Stage 2: builder ----------
FROM node:22-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time env (NEXT_PUBLIC_* must be present at build time).
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:18000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ---------- Stage 3: runtime ----------
FROM node:22-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    PORT=13000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

# node:22-alpine ships with a non-root `node` user (UID 1000).
RUN mkdir -p /app && chown -R node:node /app

# Standalone output: server.js + minimal node_modules.
COPY --from=builder --chown=node:node /app/.next/standalone ./
# Static assets and public must be copied next to the standalone bundle.
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

USER node

EXPOSE 13000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:13000/ || exit 1

CMD ["node", "server.js"]
