from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

sys.path.insert(0, os.getcwd())

from config import settings
from database.mongo import db
from database.redis_client import redis
from services.numbers.manager import PROVIDERS
from services.numbers.core.session_manager import SessionManager


async def _check_mongo() -> dict[str, Any]:
    start = datetime.now(UTC)
    try:
        await db.command("ping")
        ok = True
        error = ""
    except Exception as exc:
        ok = False
        error = str(exc)
    end = datetime.now(UTC)
    return {
        "ok": ok,
        "latency_ms": int((end - start).total_seconds() * 1000),
        "error": error,
    }


async def _check_redis() -> dict[str, Any]:
    start = datetime.now(UTC)
    key = "health:ping"
    try:
        await redis.set(key, "ok")
        value = await redis.get(key)
        ok = str(value or "") in {"ok", "'ok'"}
        error = "" if ok else f"unexpected redis response: {value!r}"
    except Exception as exc:
        ok = False
        error = str(exc)
    end = datetime.now(UTC)
    return {
        "ok": ok,
        "latency_ms": int((end - start).total_seconds() * 1000),
        "error": error,
    }


async def _provider_balance_check(provider_code: str, timeout_sec: float) -> dict[str, Any]:
    provider = PROVIDERS.get(provider_code)
    if provider is None or not hasattr(provider, "get_balance"):
        return {"provider": provider_code, "ok": False, "error": "balance_not_supported"}
    start = datetime.now(UTC)
    try:
        raw = await asyncio.wait_for(provider.get_balance(), timeout=timeout_sec)
        ok = raw is not None
        error = ""
    except Exception as exc:
        ok = False
        raw = None
        error = str(exc)
    end = datetime.now(UTC)
    return {
        "provider": provider_code,
        "ok": bool(ok),
        "latency_ms": int((end - start).total_seconds() * 1000),
        "error": error,
        "raw_type": type(raw).__name__ if raw is not None else "",
    }


async def run_health_check(*, provider_timeout_sec: float = 6.0) -> dict[str, Any]:
    mongo, redis_result = await asyncio.gather(_check_mongo(), _check_redis())
    provider_codes = sorted(PROVIDERS.keys())
    provider_results = await asyncio.gather(
        *[_provider_balance_check(code, provider_timeout_sec) for code in provider_codes]
    )
    providers_ok = sum(1 for row in provider_results if bool(row.get("ok")))
    providers_total = len(provider_results)
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "environment": str(getattr(settings, "sentry_environment", "development") or "development"),
        "mongo": mongo,
        "redis": redis_result,
        "providers": provider_results,
        "providers_ok": providers_ok,
        "providers_total": providers_total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Runtime health-check for mongo/redis/providers.")
    parser.add_argument("--provider-timeout", type=float, default=6.0, help="Timeout in seconds for provider balance checks.")
    args = parser.parse_args()
    report = asyncio.run(run_health_check(provider_timeout_sec=max(2.0, float(args.provider_timeout))))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    asyncio.run(SessionManager.close())


if __name__ == "__main__":
    main()
