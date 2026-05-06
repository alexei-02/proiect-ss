#!/usr/bin/env bash
# Run migrations, seed initial admin, then start the API server.
set -euo pipefail

echo ">> Running Prisma migrations..."
prisma migrate deploy --schema /app/prisma/schema.prisma

echo ">> Seeding initial admin (idempotent)..."
cd /app && PYTHONPATH=/app python scripts/seed_initial_admin.py || true

echo ">> Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8989 --reload
