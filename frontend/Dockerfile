# syntax=docker/dockerfile:1

# Project Goliath — frontend image.
# Multi-stage: node builds the Vite bundle, caddy serves it and proxies
# /api/* to the backend container (see deploy/Caddyfile).

FROM node:24.22.2-alpine AS build
WORKDIR /app/frontend

# Dev dependencies are installed on purpose: `npm run build` runs
# `tsc --noEmit` before `vite build`, so typescript & co must be present.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM caddy:2.11.9-alpine
COPY --from=build /app/frontend/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile

EXPOSE 80 443
