from __future__ import annotations

import aiohttp

from config import settings


class SentryAIOpsError(RuntimeError):
    pass


def ai_provider_name() -> str:
    return str(getattr(settings, "ai_provider", "openrouter") or "openrouter").strip().lower()


def ai_model_name() -> str:
    return str(getattr(settings, "openrouter_model", "openrouter/free") or "openrouter/free").strip()


def _openrouter_key() -> str:
    return str(getattr(settings, "openrouter_api_key", "") or "").strip()


def _openrouter_base() -> str:
    return str(getattr(settings, "openrouter_api_base", "https://openrouter.ai/api/v1") or "https://openrouter.ai/api/v1").rstrip("/")


def ai_is_configured() -> bool:
    if ai_provider_name() == "openrouter":
        return bool(_openrouter_key())
    return False


def ai_status_text(*, used_today: int = 0, daily_limit: int = 0) -> str:
    provider = ai_provider_name()
    model = ai_model_name()
    configured = ai_is_configured()
    lines = [
        "AI Status",
        "",
        f"Provider: {provider}",
        f"Model: {model}",
        f"Configured: {'yes' if configured else 'no'}",
    ]
    if daily_limit > 0:
        lines.append(f"Usage today: {used_today}/{daily_limit}")
    return "\n".join(lines)


async def analyze_sentry_issues_with_ai(*, issues: list[dict], hours: int) -> str:
    if not issues:
        raise SentryAIOpsError("No issues provided for analysis.")
    if ai_provider_name() != "openrouter":
        raise SentryAIOpsError(f"Unsupported AI provider: {ai_provider_name()}")
    key = _openrouter_key()
    if not key:
        raise SentryAIOpsError("OPENROUTER_API_KEY is missing.")

    issue_lines = []
    for i, item in enumerate(issues[:30], start=1):
        issue_lines.append(
            f"{i}. level={item.get('level')} title={item.get('title')} "
            f"count={item.get('count')} users={item.get('userCount')} "
            f"culprit={item.get('culprit')} lastSeen={item.get('lastSeen')} link={item.get('permalink')}"
        )
    issues_blob = "\n".join(issue_lines)
    prompt = (
        "Analyze these unresolved Sentry issues for a Telegram bot backend.\n"
        "Return concise, practical output with these sections:\n"
        "A) Highest-risk issues (top 5)\n"
        "B) Root cause hypothesis for each\n"
        "C) Fix plan in execution order\n"
        "D) Quick wins under 1 hour\n"
        "E) Post-fix monitoring checks\n\n"
        f"Window: last {hours}h\n"
        f"Issues:\n{issues_blob}"
    )

    payload = {
        "model": ai_model_name(),
        "messages": [
            {
                "role": "system",
                "content": "You are a strict production incident triage assistant for engineering teams.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    site_url = str(getattr(settings, "openrouter_site_url", "") or "").strip()
    app_title = str(getattr(settings, "openrouter_app_title", "Shop Project Bot") or "Shop Project Bot").strip()
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_title:
        headers["X-OpenRouter-Title"] = app_title

    timeout = aiohttp.ClientTimeout(total=70)
    url = f"{_openrouter_base()}/chat/completions"
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                msg = str((data or {}).get("error", {}).get("message") or f"HTTP {resp.status}")
                raise SentryAIOpsError(msg)

    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise SentryAIOpsError("OpenRouter returned no choices.")
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                txt = str(part.get("text") or "").strip()
                if txt:
                    parts.append(txt)
        merged = "\n".join(parts).strip()
        if merged:
            return merged
    raise SentryAIOpsError("OpenRouter returned empty content.")
