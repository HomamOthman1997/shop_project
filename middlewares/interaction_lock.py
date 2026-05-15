import asyncio
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, types
from aiogram.exceptions import TelegramBadRequest

from config import settings
from utils.translations import t


class InteractionLockMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._next_allowed_at: dict[int, float] = {}
        self._last_callback_sig: dict[int, tuple[str, float]] = {}
        self._inflight: set[int] = set()
        self._guard = asyncio.Lock()
        self._callback_inflight_wait_sec = max(
            0.05,
            float(getattr(settings, "interaction_lock_callback_wait_ms", 120) or 120) / 1000.0,
        )
        self._callback_inflight_poll_sec = 0.05

    @staticmethod
    def _is_arabic_text(text: str) -> bool:
        return any("\u0600" <= ch <= "\u06FF" for ch in text)

    @staticmethod
    def _text_equals_key(text: str, key: str) -> bool:
        clean = (text or "").strip()
        return clean in {t("en", key), t("ar", key)}

    def _is_main_menu_intent(self, text: str) -> bool:
        clean = (text or "").strip()
        if not clean:
            return False
        if clean.lower() in {"/start", "start"}:
            return True
        if clean.startswith("🔄"):
            return True
        return any(
            self._text_equals_key(clean, key)
            for key in ("btn_back_main", "btn_cancel", "back", "cancel")
        )

    def _is_top_level_section_trigger(self, text: str) -> bool:
        clean = (text or "").strip()
        if not clean:
            return False
        section_keys = (
            "btn_services",
            "btn_numbers",
            "btn_proxies",
            "btn_balance",
            "btn_settings",
            "btn_support",
            "btn_my_numbers",
            "btn_custom_services",
            "btn_reseller_balance",
            "btn_recharge_requests",
            "btn_reseller_settings",
            "btn_reseller_stats",
        )
        return any(self._text_equals_key(clean, key) for key in section_keys)

    def _is_side_action_intent(self, text: str) -> bool:
        clean = (text or "").strip()
        if not clean:
            return False
        return (
            self._text_equals_key(clean, "btn_support")
            or self._text_equals_key(clean, "btn_my_numbers")
            or self._text_equals_key(clean, "btn_settings")
            or clean in {t("en", "user_settings_my_account"), t("ar", "user_settings_my_account")}
        )

    def _is_fast_track_message(self, text: str) -> bool:
        clean = (text or "").strip()
        if not clean:
            return False
        return self._is_main_menu_intent(clean) or self._is_side_action_intent(clean) or self._is_top_level_section_trigger(clean)

    @staticmethod
    async def _current_state_name(data: Dict[str, Any]) -> str:
        state = data.get("state")
        if state is None or not hasattr(state, "get_state"):
            return ""
        try:
            return str(await state.get_state() or "")
        except Exception:
            return ""

    @classmethod
    async def _is_support_session(cls, data: Dict[str, Any]) -> bool:
        current_state = await cls._current_state_name(data)
        if not current_state:
            return False
        return "SupportFlow" in current_state or "SupportOwnerReplyFlow" in current_state

    async def _should_block_cross_section_message(self, event: types.Message, data: Dict[str, Any]) -> bool:
        text = (event.text or "").strip()
        if not text:
            return False
        if self._is_side_action_intent(text):
            return False
        if self._is_main_menu_intent(text):
            return False
        if not self._is_top_level_section_trigger(text):
            return False

        current_state = await self._current_state_name(data)
        if not current_state:
            return False

        lang = "ar" if self._is_arabic_text(text) else "en"
        try:
            await event.answer(t(lang, "flow_locked_main_only"))
        except Exception:
            pass
        return True

    async def __call__(
        self,
        handler: Callable[[types.Update, Dict[str, Any]], Awaitable[Any]],
        event: types.Update,
        data: Dict[str, Any],
    ) -> Any:
        if not bool(getattr(settings, "interaction_lock_enabled", True)):
            return await handler(event, data)

        user_id: int | None = None
        is_callback = False

        if isinstance(event, types.CallbackQuery):
            if event.from_user:
                user_id = int(event.from_user.id)
            is_callback = True
        elif isinstance(event, types.Message):
            if event.from_user:
                user_id = int(event.from_user.id)
        else:
            return await handler(event, data)

        if not user_id:
            return await handler(event, data)

        if isinstance(event, types.Message):
            if await self._is_support_session(data):
                return await handler(event, data)
            if await self._should_block_cross_section_message(event, data):
                return None

        now = time.monotonic()
        callback_window = max(60, int(getattr(settings, "interaction_lock_callback_window_ms", 150) or 150)) / 1000.0
        message_window = max(80, int(getattr(settings, "interaction_lock_message_window_ms", 250) or 250)) / 1000.0

        if is_callback:
            wait_deadline = now + self._callback_inflight_wait_sec
            while True:
                async with self._guard:
                    if user_id not in self._inflight:
                        break
                if time.monotonic() >= wait_deadline:
                    try:
                        await event.answer()
                    except Exception:
                        pass
                    return None
                await asyncio.sleep(self._callback_inflight_poll_sec)

        async with self._guard:
            if user_id in self._inflight:
                if is_callback:
                    try:
                        await event.answer()
                    except Exception:
                        pass
                return None

            if is_callback:
                sig = str(getattr(event, "data", "") or "")
                prev_sig, prev_ts = self._last_callback_sig.get(user_id, ("", 0.0))
                if sig and sig == prev_sig and (now - prev_ts) < callback_window:
                    try:
                        await event.answer()
                    except Exception:
                        pass
                    return None
                self._last_callback_sig[user_id] = (sig, now)
            else:
                text = str(getattr(event, "text", "") or "").strip()
                if not self._is_fast_track_message(text):
                    next_allowed = float(self._next_allowed_at.get(user_id, 0.0) or 0.0)
                    if now < next_allowed:
                        return None
                    self._next_allowed_at[user_id] = now + message_window

            self._inflight.add(user_id)

        try:
            return await handler(event, data)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                if is_callback:
                    try:
                        await event.answer()
                    except Exception:
                        pass
                return None
            raise
        finally:
            async with self._guard:
                self._inflight.discard(user_id)
                # Best effort cleanup so map does not grow forever.
                cutoff = time.monotonic() - 300
                if len(self._next_allowed_at) > 5000:
                    self._next_allowed_at = {
                        uid: ts for uid, ts in self._next_allowed_at.items() if ts >= cutoff
                    }
                if len(self._last_callback_sig) > 5000:
                    self._last_callback_sig = {
                        uid: (sig, ts)
                        for uid, (sig, ts) in self._last_callback_sig.items()
                        if ts >= cutoff
                    }
