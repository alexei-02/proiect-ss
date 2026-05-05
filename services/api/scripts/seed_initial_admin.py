#!/usr/bin/env python3
"""Idempotent initial admin seeder.

Reads INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD from the environment.
If both are set and no admin user exists yet, creates one.

Safe to run on every container start — does nothing if an admin already exists.

Usage (inside container, after prisma migrate deploy):
    python /app/scripts/seed_initial_admin.py
"""

import asyncio
import logging
import os
import sys

logging.basicConfig(level="INFO", format="%(levelname)s  %(message)s")
logger = logging.getLogger("seed_admin")


async def main() -> None:
    username = os.environ.get("INITIAL_ADMIN_USERNAME", "").strip()
    password = os.environ.get("INITIAL_ADMIN_PASSWORD", "").strip()

    if not username or not password:
        logger.info("INITIAL_ADMIN_USERNAME/PASSWORD not set — skipping admin seed.")
        return

    from prisma import Prisma

    from app.core.passwords import hash_password

    db = Prisma()
    await db.connect()
    try:
        existing = await db.user.count(where={"roles": {"has": "admin"}})
        if existing > 0:
            logger.info("Admin user already exists — nothing to do.")
            return

        await db.user.create(
            data={
                "username": username,
                "passwordHash": hash_password(password),
                "roles": ["admin"],
            }
        )
        logger.info("Created initial admin user '%s'.", username)
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
