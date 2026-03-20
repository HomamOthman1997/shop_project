from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot

from database.bot_logs_repo import get_bot_logs_target


class TelegramErrorHandler(logging.Handler):
    def __init__(self, *, bot_token: str, level: int = logging.ERROR) -> None:
        super().__init__(level=level)
        self._bot_token = str(bot_token or "").strip()
        self._bot: Bot | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_sent: dict[str, float] = {}

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def _get_bot(self) -> Bot | None:
        if not self._bot_token:
            return None
        if self._bot is None:
            self._bot = Bot(token=self._bot_token, timeout=30)
        return self._bot

    async def _emit_async(self, text: str) -> None:
        target = await get_bot_logs_target()
        if not target:
            return
        bot = await self._get_bot()
        if bot is None:
            return
        kwargs = {"chat_id": int(target["chat_id"]), "text": text[:3900]}
        thread_id = target.get("message_thread_id")
        if isinstance(thread_id, int):
            kwargs["message_thread_id"] = int(thread_id)
        try:
            await bot.send_message(**kwargs)
        except Exception:
            return

    def emit(self, record: logging.LogRecord) -> None:
        if self._loop is None or not self._bot_token:
            return
        try:
            rendered = self.format(record)
        except Exception:
            rendered = record.getMessage()
        if not rendered:
            return

        dedupe_key = f"{record.name}:{record.levelname}:{rendered[:200]}"
        now_ts = datetime.utcnow().timestamp()
        prev_ts = self._last_sent.get(dedupe_key, 0.0)
        if now_ts - prev_ts < 15.0:
            return
        self._last_sent[dedupe_key] = now_ts

        text = (
            "LOG ERROR\n\n"
            f"Level: {record.levelname}\n"
            f"Logger: {record.name}\n\n"
            f"{rendered}"
        )
        self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self._emit_async(text)))

    async def aclose(self) -> None:
        if self._bot is not None:
            await self._bot.session.close()
            self._bot = None


def install_telegram_error_handler(*, bot_token: str) -> TelegramErrorHandler | None:
    token = str(bot_token or "").strip()
    if not token:
        return None

    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, TelegramErrorHandler):
            try:
                handler.bind_loop(asyncio.get_running_loop())
            except Exception:
                pass
            return handler

    handler = TelegramErrorHandler(bot_token=token)
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.bind_loop(asyncio.get_running_loop())
    except Exception:
        pass
    root.addHandler(handler)
    return handler
