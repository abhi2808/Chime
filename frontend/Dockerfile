# Chime web: the built SPA behind Caddy, which also proxies /api and /auth to the backend
# so the whole app is one origin (the OAuth cookies depend on it). Build from the repo root:
#   docker build -f frontend/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
