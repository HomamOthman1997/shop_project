from __future__ import annotations

import aiohttp

from config import settings


class SentryIssuesError(RuntimeError):
    pass


def _api_base() -> str:
    return str(getattr(settings, "sentry_api_base", "https://sentry.io/api/0") or "https://sentry.io/api/0").rstrip("/")


def _org_slug() -> str:
    return str(getattr(settings, "sentry_org_slug", "") or "").strip()


def _project_slug() -> str:
    return str(getattr(settings, "sentry_project_slug", "") or "").strip()


def _token() -> str:
    return str(getattr(settings, "sentry_auth_token", "") or "").strip()


async def fetch_sentry_project_issues(*, hours: int = 24, limit: int = 20) -> list[dict]:
    org = _org_slug()
    project = _project_slug()
    token = _token()
    if not org or not project or not token:
        raise SentryIssuesError("Sentry API settings are incomplete (org/project/token).")

    window_hours = max(1, min(int(hours or 24), 168))
    rows_limit = max(1, min(int(limit or 20), 100))

    stats_period = "24h" if window_hours <= 24 else "14d"
    query = {
        "query": "is:unresolved",
        "sort": "freq",
        "statsPeriod": stats_period,
        "limit": str(rows_limit),
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = f"{_api_base()}/projects/{org}/{project}/issues/"
    timeout = aiohttp.ClientTimeout(total=40)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, params=query) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                message = str((data or {}).get("detail") or f"HTTP {resp.status}")
                raise SentryIssuesError(message)
    if not isinstance(data, list):
        raise SentryIssuesError("Unexpected Sentry issues response format.")
    output: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        output.append(
            {
                "id": str(row.get("id") or ""),
                "shortId": str(row.get("shortId") or ""),
                "title": str(row.get("title") or ""),
                "culprit": str(row.get("culprit") or ""),
                "level": str(row.get("level") or ""),
                "count": str(row.get("count") or ""),
                "userCount": str(row.get("userCount") or ""),
                "permalink": str(row.get("permalink") or ""),
                "lastSeen": str(row.get("lastSeen") or ""),
                "firstSeen": str(row.get("firstSeen") or ""),
            }
        )
    return output
