import atexit
import asyncio
from contextlib import suppress

import aiohttp


class SessionManager:
    _session: aiohttp.ClientSession | None = None
    _atexit_registered = False

    @classmethod
    def _ensure_atexit(cls) -> None:
        if cls._atexit_registered:
            return
        atexit.register(cls._close_at_exit)
        cls._atexit_registered = True

    @classmethod
    def _close_at_exit(cls) -> None:
        session = cls._session
        if session is None or session.closed:
            cls._session = None
            return
        with suppress(Exception):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(session.close())
            finally:
                loop.close()
        cls._session = None

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            cls._session = aiohttp.ClientSession(timeout=timeout)
            cls._ensure_atexit()
        return cls._session

    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None

    @classmethod
    async def close_session(cls):
        await cls.close()
