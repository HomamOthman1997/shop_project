from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from pymongo import ReturnDocument

from database.mongo import db
from services.platform.api_auth import ApiAuthContext


@dataclass(frozen=True)
class ApiRateLimitDecision:
    bucket: str
    limit: int
    remaining: int
    reset_at: int
    window_seconds: int


class ApiRateLimitExceeded(Exception):
    def __init__(self, decision: ApiRateLimitDecision) -> None:
        self.decision = decision
        super().__init__("api rate limit exceeded")


def _window_start(now: int, window_seconds: int) -> int:
    return now - (now % window_seconds)


async def check_api_rate_limit(
    auth: ApiAuthContext,
    *,
    bucket: str,
    limit: int,
    window_seconds: int = 60,
) -> ApiRateLimitDecision:
    if "*" in set(auth.scopes):
        return ApiRateLimitDecision(
            bucket=bucket,
            limit=limit,
            remaining=limit,
            reset_at=int(time.time()) + window_seconds,
            window_seconds=window_seconds,
        )

    now = int(time.time())
    window = _window_start(now, window_seconds)
    reset_at = window + window_seconds
    expires_at = datetime.fromtimestamp(reset_at + window_seconds, tz=UTC)
    key = f"api:{auth.key_id}:{bucket}:{window}"

    doc = await db.api_rate_limits.find_one_and_update(
        {"_id": key},
        {
            "$setOnInsert": {
                "api_key_id": auth.key_id,
                "user_id": auth.user_id,
                "reseller_id": auth.reseller_id,
                "bucket": bucket,
                "window_start": window,
                "window_seconds": window_seconds,
                "reset_at": reset_at,
                "expires_at": expires_at,
            },
            "$inc": {"count": 1},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    count = int((doc or {}).get("count") or 0)
    decision = ApiRateLimitDecision(
        bucket=bucket,
        limit=int(limit),
        remaining=max(int(limit) - count, 0),
        reset_at=reset_at,
        window_seconds=window_seconds,
    )
    if count > int(limit):
        raise ApiRateLimitExceeded(decision)
    return decision


def rate_limit_headers(decision: ApiRateLimitDecision) -> dict[str, str]:
    return {
        "X-RateLimit-Bucket": decision.bucket,
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_at),
    }


def retry_after_seconds(decision: ApiRateLimitDecision) -> int:
    return max(decision.reset_at - int(time.time()), 1)
