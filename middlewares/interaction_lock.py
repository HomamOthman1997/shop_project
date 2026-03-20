import asyncio
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, types

from config import settings
from utils.translations import t


class InteractionLockMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._next_allowed_at: dict[int, float] = {}
        self._last_callback_sig: dict[int, tuple[str, float]] = {}
        self._inflight: set[int] = set()
        self._guard = asyncio.Lock()

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
            "btn_custom_services",
            "btn_reseller_balance",
            "btn_recharge_requests",
            "btn_reseller_settings",
            "btn_reseller_stats",
        )
        return any(self._text_equals_key(clean, key) for key in section_keys)

    async def _should_block_cross_section_message(self, event: types.Message, data: Dict[str, Any]) -> bool:
        text = (event.text or "").strip()
        if not text:
            return False
        if self._is_main_menu_intent(text):
            return False
        if not self._is_top_level_section_trigger(text):
            return False

        state = data.get("state")
        if state is None or not hasattr(state, "get_state"):
            return False
        try:
            current_state = await state.get_state()
        except Exception:
            current_state = None
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
            if await self._should_block_cross_section_message(event, data):
                return None

        now = time.monotonic()
        callback_window = max(100, int(getattr(settings, "interaction_lock_callback_window_ms", 1200) or 1200)) / 1000.0
        message_window = max(100, int(getattr(settings, "interaction_lock_message_window_ms", 2500) or 2500)) / 1000.0

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
                next_allowed = float(self._next_allowed_at.get(user_id, 0.0) or 0.0)
                if now < next_allowed:
                    return None
                self._next_allowed_at[user_id] = now + message_window

            self._inflight.add(user_id)

        try:
            return await handler(event, data)
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
