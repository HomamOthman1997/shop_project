from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from services.numbers.manager import get_recording_from_provider
from services.numbers.order_service import NumbersOrderError


logger = logging.getLogger("numbers_recording_service")


RecordingDownloader = Callable[[str, str], Awaitable[dict[str, Any]]]


_VOICE_RECORDING_KEYS = {
    "recording",
    "recordinguri",
    "recordingurl",
    "recordinghref",
    "recordinglink",
    "recordingdownloadurl",
    "recordingdownloaduri",
    "recordingdownloadlink",
    "audiouri",
    "audiourl",
    "audiohref",
    "audiolink",
    "mp3url",
    "wavurl",
}


def _recording_key_matches(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(key or "").strip().lower())
    if normalized in _VOICE_RECORDING_KEYS:
        return True
    return bool(("recording" in normalized or "audio" in normalized) and any(part in normalized for part in ("uri", "url", "href", "link")))


def voice_recording_uri_from_value(value: Any, *, key: Any = "") -> str:
    key_matches = _recording_key_matches(key)

    if isinstance(value, str):
        return value.strip() if key_matches else ""

    if isinstance(value, dict):
        if key_matches:
            for item_key, item_value in value.items():
                normalized = re.sub(r"[^a-z0-9]+", "", str(item_key or "").strip().lower())
                if normalized not in {"uri", "url", "href", "link", "downloaduri", "downloadurl", "downloadlink"}:
                    continue
                if isinstance(item_value, str) and item_value.strip():
                    return item_value.strip()

        for item_key, item_value in value.items():
            if not _recording_key_matches(item_key):
                continue
            if isinstance(item_value, str) and item_value.strip():
                return item_value.strip()
            nested = voice_recording_uri_from_value(item_value, key=item_key)
            if nested:
                return nested

        for item_key, item_value in value.items():
            if not isinstance(item_value, (dict, list, tuple)):
                continue
            nested = voice_recording_uri_from_value(item_value, key=item_key)
            if nested:
                return nested

    if isinstance(value, (list, tuple)):
        for item in value:
            nested = voice_recording_uri_from_value(item, key=key)
            if nested:
                return nested

    return ""


def voice_recording_uri_from_calls(calls: Any) -> str:
    if not isinstance(calls, list):
        return ""
    for call in calls:
        if not isinstance(call, dict):
            continue
        recording_uri = voice_recording_uri_from_value(call)
        if recording_uri:
            return recording_uri
    return ""


def recording_filename(content_type: object) -> str:
    value = str(content_type or "").strip().lower()
    if "mpeg" in value or "mp3" in value:
        return "call-recording.mp3"
    if "wav" in value:
        return "call-recording.wav"
    if "ogg" in value:
        return "call-recording.ogg"
    if "mp4" in value or "m4a" in value:
        return "call-recording.m4a"
    return "call-recording.bin"


def _provider_code(order: dict[str, Any]) -> str:
    return str(order.get("provider") or order.get("provisioning_provider") or "").strip().lower()


async def download_voice_order_recording(
    order: dict[str, Any] | None,
    *,
    downloader: RecordingDownloader = get_recording_from_provider,
) -> dict[str, Any]:
    order = order if isinstance(order, dict) else {}
    if str(order.get("number_mode") or "").strip().lower() != "voice":
        raise NumbersOrderError("invalid_mode", "This action is only for call numbers.", status=400)

    provider = _provider_code(order)
    recording_uri = str(order.get("voice_recording_uri") or "").strip()
    if not provider or not recording_uri:
        raise NumbersOrderError("recording_not_ready", "No call recording is available yet.", status=404)

    try:
        data = await downloader(provider, recording_uri)
    except Exception as exc:
        logger.exception("numbers voice recording download failed order=%s", order.get("_id"))
        raise NumbersOrderError(
            "recording_download_failed",
            "Could not download the recording right now.",
            status=502,
        ) from exc

    if not isinstance(data, dict) or not data.get("success") or not data.get("content"):
        raise NumbersOrderError(
            "recording_download_failed",
            "Could not download the recording right now.",
            status=502,
        )

    content_type = str(data.get("content_type") or "application/octet-stream")
    return {
        "content": bytes(data.get("content") or b""),
        "content_type": content_type,
        "filename": recording_filename(content_type),
    }
