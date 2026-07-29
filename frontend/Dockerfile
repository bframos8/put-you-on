FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time — a wrong/empty value
# can't be corrected at runtime (gameplan 2.5). Fail loudly if the deploy build-arg is
# missing rather than shipping an image whose API calls silently hit the frontend's own
# origin. CI passes https://putyouon.app (Phase 8.2).
RUN test -n "$NEXT_PUBLIC_API_URL" || (echo 'ERROR: NEXT_PUBLIC_API_URL build-arg is required (gameplan 2.5)' >&2; exit 1) \
    && npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
# Next's standalone server.js binds to process.env.HOSTNAME, and Docker injects
# HOSTNAME=<container-id> — so without this it listens only on the container's own
# IP, and localhost/127.0.0.1 (the HEALTHCHECK below) get ECONNREFUSED. Bind to
# 0.0.0.0 so both the loopback probe and nginx's proxy to the container IP work.
ENV HOSTNAME=0.0.0.0 PORT=3000
# Drop to the image's built-in unprivileged `node` user. The standalone server only
# reads these root-owned files (world-readable) and serves — it writes nothing to /app.
USER node
# Container self-health via the standalone server's root route. Uses the image's own
# Node (no curl in node:20-alpine → no extra package). Non-200 or a connection error
# exits non-zero = unhealthy; --start-period gives the server a moment to bind :3000.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["node", "-e", "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"]
CMD ["node", "server.js"]
