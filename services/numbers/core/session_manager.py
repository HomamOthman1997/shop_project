import aiohttp


class SessionManager:
    _session: aiohttp.ClientSession | None = None

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            cls._session = aiohttp.ClientSession(timeout=timeout)
        return cls._session

    @classmethod
    async def close(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None

    @classmethod
    async def close_session(cls):
        await cls.close()
