from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from aiogram import Bot

from database.bot_logs_repo import get_bot_logs_target


class TelegramErrorHandler(logging.Handler):
    def __init__(self, *, bot_token: str, level: int = logging.ERROR) -> None:
        super().__init__(level=level)
        self._bot_token = str(bot_token or "").strip()
        self._bot: Bot | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_sent: dict[str, float] = {}
        self._closing = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def _get_bot(self) -> Bot | None:
        if not self._bot_token:
            return None
        if self._bot is None:
            self._bot = Bot(token=self._bot_token)
        return self._bot

    async def _emit_async(self, text: str) -> None:
        if self._closing:
            return
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

    @staticmethod
    def _is_transient_polling_noise(record: logging.LogRecord, rendered: str) -> bool:
        logger_name = str(record.name or "").strip().lower()
        text = str(rendered or "").strip().lower()
        if not logger_name.startswith("aiogram.dispatcher"):
            return False
        return (
            "failed to fetch updates" in text
            and (
                "telegramnetworkerror" in text
                or "telegramconflicterror" in text
                or "terminated by other getupdates request" in text
                or "server disconnected" in text
                or "cannot connect to host api.telegram.org" in text
                or "clientconnectordnserror" in text
                or "connection reset by peer" in text
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        if self._closing or self._loop is None or not self._bot_token:
            return
        try:
            rendered = self.format(record)
        except Exception:
            rendered = record.getMessage()
        if not rendered:
            return
        if self._is_transient_polling_noise(record, rendered):
            return

        dedupe_key = f"{record.name}:{record.levelname}:{rendered[:200]}"
        now_ts = datetime.now(UTC).timestamp()
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
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self._emit_async(text)))
        except RuntimeError:
            # Event loop can be closing during KeyboardInterrupt/SystemExit shutdown.
            return

    async def aclose(self) -> None:
        self._closing = True
        root = logging.getLogger()
        with contextlib.suppress(Exception):
            root.removeHandler(self)
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
