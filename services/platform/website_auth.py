from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import logging
import re
import secrets
from typing import Any
from urllib.parse import quote
from uuid import uuid4
from pathlib import Path

from aiohttp import ClientSession, web
from pymongo.errors import DuplicateKeyError

from config import settings
from database.website_auth_repo import (
    consume_telegram_link_token,
    consume_email_verification_token,
    consume_website_auth_rate_limit,
    create_email_verification_token,
    allocate_website_customer_id,
    create_telegram_link_token,
    create_website_account,
    create_website_user_profile,
    create_website_session,
    create_identity_verification_request,
    store_identity_document,
    delete_website_session,
    delete_other_website_sessions,
    find_website_account_by_email,
    find_website_account_by_id,
    find_website_session,
    find_latest_identity_verification,
    link_telegram_account,
    mark_website_email_verified,
    unlink_telegram_account,
    update_website_account_language,
    update_website_account_password,
)
from database.customer_conversations_repo import (
    DIRECTION_CUSTOMER,
    append_message as _conversation_append_message,
    get_conversation_for_customer,
    get_or_create_conversation,
    list_messages as _conversation_list_messages,
    mark_conversation_read,
)
from database.notifications_repo import (
    RECIPIENT_CUSTOMER,
    list_notifications as _list_notifications,
    mark_all_read as _notifications_mark_all_read,
    notify_owner,
    unread_count as _notifications_unread_count,
)

from services.digital_products.reseller_pricing import TIERS as _RESELLER_TIERS_TUPLE

logger = logging.getLogger(__name__)

_RESELLER_TIERS = frozenset(_RESELLER_TIERS_TUPLE)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SESSION_DAYS = 30
_LINK_MINUTES = 10
_EMAIL_CODE_MINUTES = 15
_SESSION_COOKIE = "phantom_session"
_CSRF_COOKIE = "phantom_csrf"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_AUTH_STATIC = Path(__file__).resolve().parents[2] / "webapp" / "auth"
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
}
# HSTS only in production (HTTPS guaranteed behind the edge); avoids forcing HTTPS in local/dev.
if bool(getattr(settings, "production_mode", False)):
    _SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


def _auth_error(message: str, *, status: int) -> web.Response:
    return web.json_response({"ok": False, "message": message}, status=status)


async def _read_json_body(request: web.Request) -> dict[str, Any] | web.Response:
    try:
        body = await request.json()
    except Exception:
        return _auth_error("invalid json body", status=400)
    return body if isinstance(body, dict) else _auth_error("json object required", status=400)


@dataclass(frozen=True)
class WebsiteAuthContext:
    account_id: str
    customer_id: int
    email: str
    telegram_id: int | None
    session_token_hash: str
    reseller_tier: str = ""  # "" for a normal customer; a tier name for a wholesale reseller


def _now() -> datetime:
    return datetime.now(UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise web.HTTPBadRequest(text="invalid email")
    return email


def _validate_password(value: Any) -> str:
    password = str(value or "")
    if len(password) < 10 or len(password) > 256:
        raise web.HTTPBadRequest(text="password must be between 10 and 256 characters")
    return password


def _password_hash(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt.hex(), digest.hex()


def _password_matches(password: str, account: dict[str, Any]) -> bool:
    try:
        _, candidate = _password_hash(password, str(account.get("password_salt") or ""))
    except Exception:
        return False
    return hmac.compare_digest(candidate, str(account.get("password_hash") or ""))


def _public_account(account: dict[str, Any]) -> dict[str, Any]:
    telegram_id = account.get("telegram_id")
    email_verified_at = account.get("email_verified_at")
    email_verified = isinstance(email_verified_at, datetime)
    is_owner = _is_owner_email(account.get("email_normalized") or account.get("email"))
    reseller_tier = str(account.get("reseller_tier") or "").strip().lower()
    is_reseller = reseller_tier in _RESELLER_TIERS
    return {
        "account_id": str(account.get("_id") or ""),
        "customer_id": int(account.get("customer_id") or 0),
        "email": str(account.get("email") or ""),
        "telegram_linked": bool(telegram_id),
        "telegram_id": int(telegram_id) if telegram_id else None,
        "email_verified": email_verified,
        "email_verified_at": email_verified_at.isoformat() if isinstance(email_verified_at, datetime) else None,
        "status": str(account.get("status") or "active"),
        "language": "ar" if str(account.get("language") or "ar").strip().lower().startswith("ar") else "en",
        "identity_status": str(account.get("identity_status") or "not_submitted"),
        "is_owner": is_owner,
        "is_reseller": is_reseller,
        "reseller_tier": reseller_tier if is_reseller else "",
        "capabilities": {
            "buy_services": email_verified,
            "sell_cards": str(account.get("identity_status") or "") == "approved",
            "owner_dashboard": email_verified and is_owner,
            "wholesale_pricing": is_reseller,
        },
    }


def _is_owner_email(value: Any) -> bool:
    email = str(value or "").strip().lower()
    owner_email = str(getattr(settings, "website_owner_email", "") or "").strip().lower()
    return bool(email and owner_email and hmac.compare_digest(email, owner_email))


async def _issue_session(account: dict[str, Any]) -> str:
    now = _now()
    account_id = str(account.get("_id") or "").strip()
    if not account_id:
        raise web.HTTPInternalServerError(text="account id is missing")
    for _attempt in range(3):
        token = secrets.token_urlsafe(32)
        try:
            await create_website_session(
                {
                    "_id": str(uuid4()),
                    "account_id": account_id,
                    "token_hash": _token_hash(token),
                    "created_at": now,
                    "expires_at": now + timedelta(days=_SESSION_DAYS),
                }
            )
            return token
        except DuplicateKeyError:
            continue
    raise web.HTTPInternalServerError(text="could not create session")


def _extract_bearer(request: web.Request) -> str:
    auth = str(request.headers.get("Authorization") or "").strip()
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _secure_cookie() -> bool:
    return bool(getattr(settings, "production_mode", False))


def _set_auth_cookies(response: web.StreamResponse, *, session_token: str, csrf_token: str) -> None:
    max_age = _SESSION_DAYS * 24 * 60 * 60
    response.set_cookie(
        _SESSION_COOKIE,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=_secure_cookie(),
        samesite="Strict",
        path="/",
    )
    response.set_cookie(
        _CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=_secure_cookie(),
        samesite="Strict",
        path="/",
    )


def _clear_auth_cookies(response: web.StreamResponse) -> None:
    response.del_cookie(_SESSION_COOKIE, path="/")
    response.del_cookie(_CSRF_COOKIE, path="/")


async def _enforce_rate_limit(request: web.Request, *, bucket: str, discriminator: str = "", limit: int) -> None:
    remote = str(request.remote or request.headers.get("X-Forwarded-For") or "unknown").split(",", 1)[0].strip()
    subject_hash = _token_hash(f"{remote}:{discriminator}")
    try:
        allowed = await consume_website_auth_rate_limit(subject_hash, bucket=bucket, limit=limit)
    except Exception:
        logger.warning("website auth rate limit storage failed for bucket=%s", bucket, exc_info=True)
        return
    if not allowed:
        raise web.HTTPTooManyRequests(text="too many requests", headers={"Retry-After": "60"})


async def require_website_auth(request: web.Request) -> WebsiteAuthContext:
    bearer_token = _extract_bearer(request)
    token = bearer_token or str(request.cookies.get(_SESSION_COOKIE) or "")
    if not token:
        raise web.HTTPUnauthorized(text="missing session")
    if not bearer_token and request.method.upper() not in _SAFE_METHODS:
        csrf_cookie = str(request.cookies.get(_CSRF_COOKIE) or "")
        csrf_header = str(request.headers.get("X-CSRF-Token") or "")
        if not csrf_cookie or not hmac.compare_digest(csrf_cookie, csrf_header):
            raise web.HTTPForbidden(text="invalid csrf token")
    token_hash = _token_hash(token)
    session = await find_website_session(token_hash, now=_now())
    if not session:
        raise web.HTTPUnauthorized(text="invalid session")
    account = await find_website_account_by_id(str(session.get("account_id") or ""))
    if not account or str(account.get("status") or "active") != "active":
        raise web.HTTPUnauthorized(text="invalid account")
    telegram_id = account.get("telegram_id")
    account_tier = str(account.get("reseller_tier") or "").strip().lower()
    return WebsiteAuthContext(
        account_id=str(account["_id"]),
        customer_id=int(account.get("customer_id") or 0),
        email=str(account.get("email") or ""),
        telegram_id=int(telegram_id) if telegram_id else None,
        session_token_hash=token_hash,
        reseller_tier=account_tier if account_tier in _RESELLER_TIERS else "",
    )


async def require_website_purchase_ready(request: web.Request) -> None:
    if not str(request.cookies.get(_SESSION_COOKIE) or ""):
        return
    await require_website_email_verified(request)


async def require_website_email_verified(request: web.Request) -> WebsiteAuthContext:
    auth = await require_website_auth(request)
    account = await find_website_account_by_id(auth.account_id) or {}
    if isinstance(account.get("email_verified_at"), datetime):
        return auth
    raise web.HTTPForbidden(
        text="email verification required",
        content_type="text/plain",
    )


async def require_website_owner(request: web.Request) -> WebsiteAuthContext:
    auth = await require_website_email_verified(request)
    if _is_owner_email(auth.email):
        return auth
    raise web.HTTPForbidden(text="owner only", content_type="text/plain")


def _email_code_hash(account_id: str, code: str) -> str:
    return _token_hash(f"email-code:{account_id}:{str(code or '').strip()}")


def _generate_email_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def _deliver_email_verification_code(*, email: str, code: str) -> dict[str, Any]:
    api_key = str(getattr(settings, "resend_api_key", "") or "").strip()
    sender = str(getattr(settings, "transactional_email_from", "") or "").strip()
    provider = str(getattr(settings, "transactional_email_provider", "none") or "none").strip().lower()
    if provider == "none" and api_key:
        provider = "resend"
    if provider != "resend":
        return {"provider": provider or "none", "status": "stored_only"}
    if not api_key or not sender:
        return {"provider": "resend", "status": "not_configured"}
    payload = {
        "from": sender,
        "to": [email],
        "subject": "Phantom email verification code",
        "text": f"Your Phantom verification code is: {code}\nThis code expires in {_EMAIL_CODE_MINUTES} minutes.",
        "html": f"<p>Your Phantom verification code is:</p><h2>{code}</h2><p>This code expires in {_EMAIL_CODE_MINUTES} minutes.</p>",
    }
    try:
        async with ClientSession() as session:
            async with session.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=10,
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    return {"provider": "resend", "status": "failed", "status_code": response.status, "error": body[:240]}
                return {"provider": "resend", "status": "sent"}
    except Exception as exc:
        return {"provider": "resend", "status": "failed", "error": str(exc)[:240]}


async def register(request: web.Request) -> web.Response:
    body = await _read_json_body(request)
    if isinstance(body, web.Response):
        return body
    try:
        email = _normalize_email(body.get("email"))
    except web.HTTPBadRequest:
        return _auth_error("invalid email", status=400)
    await _enforce_rate_limit(request, bucket="register", discriminator=email, limit=5)
    try:
        password = _validate_password(body.get("password"))
    except web.HTTPBadRequest:
        return _auth_error("password must be between 10 and 256 characters", status=400)
    salt, password_hash = _password_hash(password)
    now = _now()
    customer_id = await allocate_website_customer_id()
    account = {
        "_id": str(uuid4()),
        "customer_id": customer_id,
        "email": email,
        "email_normalized": email,
        "password_salt": salt,
        "password_hash": password_hash,
        "status": "active",
        "identity_status": "not_submitted",
        "created_at": now,
        "updated_at": now,
    }
    try:
        await create_website_account(account)
        await create_website_user_profile(customer_id=customer_id, email=email, now=now)
    except DuplicateKeyError:
        raise web.HTTPConflict(text="email already registered")
    token = await _issue_session(account)
    response = web.json_response({"account": _public_account(account)}, status=201)
    _set_auth_cookies(response, session_token=token, csrf_token=secrets.token_urlsafe(24))
    return response


async def login(request: web.Request) -> web.Response:
    body = await _read_json_body(request)
    if isinstance(body, web.Response):
        return body
    try:
        email = _normalize_email(body.get("email"))
    except web.HTTPBadRequest:
        return _auth_error("invalid email", status=400)
    await _enforce_rate_limit(request, bucket="login", discriminator=email, limit=10)
    try:
        password = _validate_password(body.get("password"))
    except web.HTTPBadRequest:
        return _auth_error("password must be between 10 and 256 characters", status=400)
    account = await find_website_account_by_email(email)
    if not account or not _password_matches(password, account) or str(account.get("status") or "active") != "active":
        raise web.HTTPUnauthorized(text="invalid credentials")
    token = await _issue_session(account)
    response = web.json_response({"account": _public_account(account)})
    _set_auth_cookies(response, session_token=token, csrf_token=secrets.token_urlsafe(24))
    return response


async def me(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    account = await find_website_account_by_id(auth.account_id)
    conversation = await get_conversation_for_customer(auth.customer_id)
    unread = int((conversation or {}).get("customer_unread") or 0)
    notifications_unread = await _notifications_unread_count(
        recipient_type=RECIPIENT_CUSTOMER, recipient_id=auth.customer_id, exclude_kinds=_CHAT_NOTIFICATION_KINDS
    )
    return web.json_response(
        {
            "account": _public_account(account or {}),
            "conversation_unread": unread,
            "notifications_unread": int(notifications_unread),
        }
    )


async def logout(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    await delete_website_session(auth.session_token_hash)
    response = web.json_response({"ok": True})
    _clear_auth_cookies(response)
    return response


async def create_link(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    if auth.telegram_id:
        raise web.HTTPConflict(text="telegram already linked")
    raw_token = secrets.token_hex(16)
    now = _now()
    await create_telegram_link_token(
        {
            "_id": str(uuid4()),
            "account_id": auth.account_id,
            "token_hash": _token_hash(raw_token),
            "created_at": now,
            "expires_at": now + timedelta(minutes=_LINK_MINUTES),
            "used_at": None,
        }
    )
    payload = f"link_{raw_token}"
    username = str(getattr(settings, "main_bot_username", "") or "").strip().lstrip("@")
    url = f"https://t.me/{quote(username)}?start={payload}" if username else None
    return web.json_response({"telegram_url": url, "start_payload": payload, "expires_in_seconds": _LINK_MINUTES * 60})


async def unlink(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    await unlink_telegram_account(auth.account_id, now=_now())
    return web.json_response({"ok": True})


async def update_language(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    body = await _read_json_body(request)
    if isinstance(body, web.Response):
        return body
    language = str((body or {}).get("language") or "").strip().lower()
    if language not in {"ar", "en"}:
        return _auth_error("invalid language", status=400)
    account = await update_website_account_language(auth.account_id, auth.customer_id, language, now=_now())
    return web.json_response({"ok": True, "account": _public_account(account or {})})


async def change_password(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    await _enforce_rate_limit(request, bucket="password_change", discriminator=auth.account_id, limit=6)
    body = await _read_json_body(request)
    if isinstance(body, web.Response):
        return body
    current_password = str((body or {}).get("current_password") or "")
    try:
        new_password = _validate_password((body or {}).get("new_password"))
    except web.HTTPBadRequest:
        return _auth_error("password must be between 10 and 256 characters", status=400)
    if not current_password:
        return _auth_error("current password required", status=400)
    if hmac.compare_digest(current_password, new_password):
        return _auth_error("new password must be different", status=400)
    account = await find_website_account_by_id(auth.account_id)
    if not account or not _password_matches(current_password, account):
        raise web.HTTPUnauthorized(text="invalid current password")
    salt, password_hash = _password_hash(new_password)
    updated = await update_website_account_password(auth.account_id, salt=salt, password_hash=password_hash, now=_now())
    # Revoke every other session so a stolen/old session cannot outlive the password change.
    await delete_other_website_sessions(auth.account_id, keep_token_hash=auth.session_token_hash)
    return web.json_response({"ok": True, "account": _public_account(updated or account)})


async def send_email_code(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    account = await find_website_account_by_id(auth.account_id) or {}
    if isinstance(account.get("email_verified_at"), datetime):
        return web.json_response({"ok": True, "status": "already_verified"})
    email = str(account.get("email") or auth.email or "").strip().lower()
    if not email:
        raise web.HTTPBadRequest(text="missing email")
    await _enforce_rate_limit(request, bucket="email_code_send", discriminator=auth.account_id, limit=4)
    code = _generate_email_code()
    now = _now()
    await create_email_verification_token(
        {
            "_id": str(uuid4()),
            "account_id": auth.account_id,
            "customer_id": auth.customer_id,
            "email": email,
            "code_hash": _email_code_hash(auth.account_id, code),
            "created_at": now,
            "expires_at": now + timedelta(minutes=_EMAIL_CODE_MINUTES),
            "used_at": None,
        }
    )
    delivery = await _deliver_email_verification_code(email=email, code=code)
    payload: dict[str, Any] = {
        "ok": True,
        "status": str(delivery.get("status") or "stored_only"),
        "provider": str(delivery.get("provider") or "none"),
        "expires_in_seconds": _EMAIL_CODE_MINUTES * 60,
    }
    if not bool(getattr(settings, "production_mode", False)) and payload["status"] != "sent":
        payload["debug_code"] = code
    if payload["status"] == "failed":
        payload["message"] = str(delivery.get("error") or "email delivery failed")
        return web.json_response(payload, status=502)
    return web.json_response(payload)


async def verify_email_code(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    await _enforce_rate_limit(request, bucket="email_code_verify", discriminator=auth.account_id, limit=10)
    body = await _read_json_body(request)
    if isinstance(body, web.Response):
        return body
    code = str((body or {}).get("code") or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{6}", code):
        raise web.HTTPBadRequest(text="invalid code")
    now = _now()
    token = await consume_email_verification_token(auth.account_id, _email_code_hash(auth.account_id, code), now=now)
    if not token:
        raise web.HTTPUnauthorized(text="invalid or expired code")
    account = await mark_website_email_verified(auth.account_id, now=now)
    return web.json_response({"ok": True, "account": _public_account(account or {})})


async def identity_status(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    account = await find_website_account_by_id(auth.account_id)
    latest = await find_latest_identity_verification(auth.account_id)
    return web.json_response(
        {
            "status": str((account or {}).get("identity_status") or "not_submitted"),
            "submitted_at": (latest or {}).get("created_at").isoformat() if isinstance((latest or {}).get("created_at"), datetime) else None,
            "review_note": str((latest or {}).get("review_note") or ""),
        }
    )


async def submit_identity(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    account = await find_website_account_by_id(auth.account_id) or {}
    if str(account.get("identity_status") or "") in {"pending", "approved"}:
        raise web.HTTPConflict(text="identity request already active")
    body = await _read_json_body(request)
    if isinstance(body, web.Response):
        return body
    full_name = " ".join(str(body.get("full_name") or "").strip().split())
    birth_date = str(body.get("birth_date") or "").strip()
    country = str(body.get("country") or "").strip()
    id_type = str(body.get("id_type") or "").strip()
    if len(full_name) < 5 or not birth_date or len(country) < 2 or id_type not in {"national_id", "passport"}:
        raise web.HTTPBadRequest(text="invalid identity request")
    doc_bytes, doc_mime = _parse_identity_document(body.get("document"))
    now = _now()
    request_id = str(uuid4())
    await create_identity_verification_request(
        {
            "_id": request_id,
            "account_id": auth.account_id,
            "customer_id": auth.customer_id,
            "full_name": full_name,
            "birth_date": birth_date,
            "country": country,
            "id_type": id_type,
            "has_document": True,
            "status": "pending",
            "created_at": now,
        }
    )
    await store_identity_document(
        request_id,
        data=doc_bytes,
        mime=doc_mime,
        account_id=auth.account_id,
        created_at=now,
    )
    await notify_owner(
        kind="identity",
        title="طلب تأكيد هوية جديد",
        body=full_name,
        link="/admin/users",
        meta={"customer_id": auth.customer_id, "request_id": request_id},
    )
    return web.json_response({"ok": True, "status": "pending"}, status=201)


_IDENTITY_DOC_RE = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", re.DOTALL)
_IDENTITY_DOC_MIN = 1024
_IDENTITY_DOC_MAX = 5 * 1024 * 1024


def _parse_identity_document(value: Any) -> tuple[bytes, str]:
    """Validate the attached ID photo (a base64 data URL) and return its bytes."""
    match = _IDENTITY_DOC_RE.match(str(value or "").strip())
    if not match:
        raise web.HTTPBadRequest(text="identity document image is required")
    mime = match.group(1)
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad request
        raise web.HTTPBadRequest(text="invalid identity document") from exc
    if not (_IDENTITY_DOC_MIN <= len(raw) <= _IDENTITY_DOC_MAX):
        raise web.HTTPBadRequest(text="identity document size invalid")
    return raw, mime


_CONVERSATION_MESSAGE_MAX = 3500


def _conversation_message_payload(row: dict[str, Any]) -> dict[str, Any]:
    direction = str(row.get("direction") or "")
    created_at = row.get("created_at")
    return {
        "id": str(row.get("_id") or ""),
        "actor": "support" if direction == "owner_to_customer" else "you",
        "text": str(row.get("text") or ""),
        "order_ref": str(row.get("order_ref") or ""),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else "",
    }


def _conversation_payload(conversation: dict[str, Any]) -> dict[str, Any]:
    last_at = conversation.get("last_message_at")
    return {
        "id": str(conversation.get("_id") or ""),
        "status": str(conversation.get("status") or "open"),
        "unread": int(conversation.get("customer_unread") or 0),
        "last_message_at": last_at.isoformat() if isinstance(last_at, datetime) else "",
    }


async def conversation_detail(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    account = await find_website_account_by_id(auth.account_id) or {}
    conversation = await get_or_create_conversation(
        customer_id=auth.customer_id,
        account_id=auth.account_id,
        customer_email=str(account.get("email") or auth.email or ""),
    )
    rows = await _conversation_list_messages(conversation["_id"])
    await mark_conversation_read(conversation["_id"], side="customer")
    return web.json_response(
        {
            "ok": True,
            "conversation": {**_conversation_payload(conversation), "unread": 0},
            "messages": [_conversation_message_payload(row) for row in rows],
        }
    )


async def conversation_send_message(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    await _enforce_rate_limit(request, bucket="conversation_send", discriminator=auth.account_id, limit=30)
    body = await _read_json_body(request)
    if isinstance(body, web.Response):
        return body
    # Normalize whitespace per line but KEEP line breaks — the guided-intake
    # wizard sends a multi-line summary the owner must read as a list.
    raw_text = str(body.get("text") or "")
    text = "\n".join(" ".join(line.split()) for line in raw_text.splitlines() if line.strip())
    if len(text) < 1:
        raise web.HTTPBadRequest(text="empty message")
    if len(text) > _CONVERSATION_MESSAGE_MAX:
        text = text[:_CONVERSATION_MESSAGE_MAX]
    order_ref = str(body.get("order_ref") or "").strip()[:120]
    account = await find_website_account_by_id(auth.account_id) or {}
    conversation = await get_or_create_conversation(
        customer_id=auth.customer_id,
        account_id=auth.account_id,
        customer_email=str(account.get("email") or auth.email or ""),
    )
    await _conversation_append_message(
        conversation,
        direction=DIRECTION_CUSTOMER,
        actor_id=auth.customer_id,
        text=text,
        order_ref=order_ref,
    )
    rows = await _conversation_list_messages(conversation["_id"])
    # Let the owner know a customer wrote in.
    await notify_owner(
        kind="conversation",
        title="رسالة جديدة من زبون",
        body=text[:120],
        link="/admin/support",
        meta={"customer_id": auth.customer_id, "conversation_id": str(conversation.get("_id") or "")},
    )
    return web.json_response(
        {
            "ok": True,
            "conversation": {**_conversation_payload(conversation), "unread": 0},
            "messages": [_conversation_message_payload(row) for row in rows],
        },
        status=201,
    )


def _notification_payload(row: dict[str, Any]) -> dict[str, Any]:
    created_at = row.get("created_at")
    return {
        "id": str(row.get("_id") or ""),
        "kind": str(row.get("kind") or ""),
        "title": str(row.get("title") or ""),
        "body": str(row.get("body") or ""),
        "link": str(row.get("link") or ""),
        "read": bool(row.get("read")),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else "",
    }


# Chat traffic (direct conversation + legacy support tickets) never lands in the
# customer bell: the مراسلة nav badge is its live counter. Order/wallet/identity
# events keep the bell.
_CHAT_NOTIFICATION_KINDS = ("conversation", "support")


async def notifications_list(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    rows = await _list_notifications(
        recipient_type=RECIPIENT_CUSTOMER, recipient_id=auth.customer_id, limit=40, exclude_kinds=_CHAT_NOTIFICATION_KINDS
    )
    unread = await _notifications_unread_count(
        recipient_type=RECIPIENT_CUSTOMER, recipient_id=auth.customer_id, exclude_kinds=_CHAT_NOTIFICATION_KINDS
    )
    return web.json_response(
        {"ok": True, "unread": int(unread), "notifications": [_notification_payload(row) for row in rows]}
    )


async def notifications_mark_read(request: web.Request) -> web.Response:
    auth = await require_website_auth(request)
    await _notifications_mark_all_read(recipient_type=RECIPIENT_CUSTOMER, recipient_id=auth.customer_id)
    return web.json_response({"ok": True, "unread": 0})


async def consume_telegram_link(payload: str, *, telegram_id: int) -> dict[str, Any]:
    raw_token = str(payload or "").strip()
    if raw_token.startswith("link_"):
        raw_token = raw_token[5:]
    if not re.fullmatch(r"[0-9a-f]{32}", raw_token):
        return {"ok": False, "reason": "invalid"}
    now = _now()
    link = await consume_telegram_link_token(_token_hash(raw_token), now=now)
    if not link:
        return {"ok": False, "reason": "expired_or_used"}
    account_id = str(link.get("account_id") or "")
    try:
        linked = await link_telegram_account(account_id, int(telegram_id), now=now)
    except DuplicateKeyError:
        return {"ok": False, "reason": "telegram_already_linked"}
    if not linked:
        return {"ok": False, "reason": "account_already_linked"}
    return {"ok": True, "account_id": account_id}


async def auth_page(_request: web.Request) -> web.Response:
    return web.Response(
        body=(_AUTH_STATIC / "index.html").read_bytes(),
        content_type="text/html",
        headers=dict(_SECURITY_HEADERS),
    )


async def auth_static(request: web.Request) -> web.Response:
    name = str(request.match_info.get("name") or "")
    path = (_AUTH_STATIC / name).resolve()
    if _AUTH_STATIC.resolve() not in path.parents or not path.is_file():
        # no-store so the CDN never caches a 404 (an image added later must serve)
        return web.Response(status=404, text="404: Not Found", headers={"Cache-Control": "no-store"})
    content_types = {
        ".css": "text/css",
        ".js": "application/javascript",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".gif": "image/gif",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
    }
    return web.Response(
        body=path.read_bytes(),
        content_type=content_types.get(path.suffix.lower(), "application/octet-stream"),
        headers=dict(_SECURITY_HEADERS),
    )


def register_website_auth_routes(app: web.Application) -> None:
    app.router.add_get("/login", auth_page)
    app.router.add_get("/register", auth_page)
    app.router.add_get("/account", auth_page)
    app.router.add_get("/app", auth_page)
    app.router.add_get("/app/{tail:.*}", auth_page)
    app.router.add_get("/admin", auth_page)
    app.router.add_get("/admin/{tail:.*}", auth_page)
    app.router.add_get("/auth/static/{name:.*}", auth_static)
    app.router.add_post("/api/v1/auth/register", register)
    app.router.add_post("/api/v1/auth/login", login)
    app.router.add_post("/api/v1/auth/logout", logout)
    app.router.add_get("/api/v1/auth/me", me)
    app.router.add_post("/api/v1/auth/language", update_language)
    app.router.add_post("/api/v1/auth/password", change_password)
    app.router.add_post("/api/v1/auth/telegram/link", create_link)
    app.router.add_delete("/api/v1/auth/telegram/link", unlink)
    app.router.add_post("/api/v1/auth/email/send-code", send_email_code)
    app.router.add_post("/api/v1/auth/email/verify", verify_email_code)
    app.router.add_get("/api/v1/auth/identity", identity_status)
    app.router.add_post("/api/v1/auth/identity", submit_identity)
    app.router.add_get("/api/v1/auth/conversation", conversation_detail)
    app.router.add_post("/api/v1/auth/conversation/messages", conversation_send_message)
    app.router.add_get("/api/v1/auth/notifications", notifications_list)
    app.router.add_post("/api/v1/auth/notifications/read", notifications_mark_read)
