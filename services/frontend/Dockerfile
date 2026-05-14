# Production multi-stage build for the Next.js dashboard.
# Stage 1 — install deps & build the static + server output
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Stage 2 — minimal runtime image
FROM node:20-alpine AS runner
WORKDIR /app

# Run as non-root
RUN addgroup -S app && adduser -S -G app app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Copy only what the standalone server needs (no /public directory in this project)
COPY --from=builder --chown=app:app /app/.next ./.next
COPY --from=builder --chown=app:app /app/node_modules ./node_modules
COPY --from=builder --chown=app:app /app/package.json ./package.json
COPY --from=builder --chown=app:app /app/next.config.js ./next.config.js

USER app
EXPOSE 3000
CMD ["npm", "start"]
