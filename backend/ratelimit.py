"""
ratelimit.py — per-farmer request limits for the expensive endpoints.

/diagnose runs CPU inference and /chat, /voice/* call paid LLM / STT APIs, so one
account (or a leaked token) must not be able to run up the bill or starve other
farmers. Counters live in DynamoDB (database.rate_limit_ok), so the limit holds
across every server instance.

Fails OPEN: if the limiter itself is down we log and let the request through, because
the endpoints are already behind login and a DynamoDB blip should not take the app
down. (The OTP limiter in routers/auth.py fails closed, since SMS costs money.)
"""

import logging
import os

from fastapi import Depends, HTTPException

import database
from auth_service import Farmer, current_farmer

logger = logging.getLogger(__name__)

# Per-farmer budgets: (requests, window seconds). Tunable without a redeploy of code.
PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))
PER_DAY = int(os.environ.get("RATE_LIMIT_PER_DAY", "200"))


def limit_farmer(bucket: str, per_minute: int = PER_MINUTE, per_day: int = PER_DAY):
    """FastAPI dependency: the logged-in farmer, or 429 when over `bucket`'s limits."""

    async def dependency(farmer: Farmer = Depends(current_farmer)) -> Farmer:
        for limit, window in ((per_minute, 60), (per_day, 86400)):
            try:
                ok = await database.rate_limit_ok(f"{bucket}#{farmer.user_id}#{window}", limit, window)
            except Exception as exc:
                logger.error("Rate limiter unavailable, allowing request: %s", exc)
                return farmer
            if not ok:
                raise HTTPException(
                    status_code=429,
                    detail="too_many_requests",
                    headers={"Retry-After": str(min(window, 60))},
                )
        return farmer

    return dependency
