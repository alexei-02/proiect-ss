#!/usr/bin/env bash
# Run migrations then start the API server.
set -euo pipefail

echo ">> Running Prisma migrations..."
prisma migrate deploy --schema /app/prisma/schema.prisma

echo ">> Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8989 --reload
