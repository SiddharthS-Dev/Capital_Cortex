# Web UI: static Vite build served by nginx, /v1 proxied to the API (same origin, so no CORS needed).
# Build context: apps/web
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# the UI grew in Phase 3: give tsc + vite enough heap (default ~2 GB is not)
ENV NODE_OPTIONS=--max-old-space-size=4096
RUN npm run build

# nginx stable line (1.30, Alpine 3.24); apk upgrade picks up Alpine security fixes released after the tag
# (Trivy HIGH/CRITICAL, docs/SECURITY_SCAN.md).
FROM nginx:1.30-alpine
RUN apk upgrade --no-cache
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=build /app/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/nginx/15-cortex-config.envsh /docker-entrypoint.d/15-cortex-config.envsh
RUN chmod +x /docker-entrypoint.d/15-cortex-config.envsh
ENV API_UPSTREAM=http://api:8000 OIDC_AUTHORITY=http://localhost:8380/realms/cortex OIDC_CLIENT_ID=cortex-web
EXPOSE 8080
