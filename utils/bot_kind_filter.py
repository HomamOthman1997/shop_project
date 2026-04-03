from __future__ import annotations

from aiogram.filters import BaseFilter

from utils.bot_menu_context import resolve_bot_kind


class BotKindFilter(BaseFilter):
    def __init__(self, *allowed_kinds: str):
        self.allowed_kinds = {str(kind or "").strip().lower() for kind in allowed_kinds if str(kind or "").strip()}

    async def __call__(self, event, bot) -> bool:
        kind = str(await resolve_bot_kind(bot) or "").strip().lower()
        return kind in self.allowed_kinds
