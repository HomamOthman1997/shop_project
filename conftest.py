import asyncio
import os
import socket

import pytest


@pytest.fixture(autouse=True)
def isolate_usage_stats_files(tmp_path, monkeypatch):
    usage_file = tmp_path / "usage_stats.json"
    top_file = tmp_path / "top_services.json"

    from utils import services_keyboard, usage_stats_manager

    monkeypatch.setattr(usage_stats_manager, "USAGE_FILE", str(usage_file))
    monkeypatch.setattr(usage_stats_manager, "TOP_FILE", str(top_file))
    monkeypatch.setattr(services_keyboard, "USAGE_FILE", str(usage_file))
    monkeypatch.setattr(services_keyboard, "TOP_FILE", str(top_file))


if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if hasattr(socket, "_LOCALHOST"):
        socket._LOCALHOST = "127.0.0.1"
    if hasattr(socket, "_LOCALHOST_V6"):
        socket._LOCALHOST_V6 = "::1"

    _orig_socketpair = socket.socketpair

    def _ipv6_socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        if family not in {socket.AF_INET, socket.AF_INET6} or type != socket.SOCK_STREAM or proto != 0:
            return _orig_socketpair(family, type, proto)

        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM, proto)
        try:
            listener.bind(("::1", 0))
            listener.listen(1)
            client = socket.socket(socket.AF_INET6, socket.SOCK_STREAM, proto)
            try:
                client.setblocking(False)
                try:
                    client.connect(listener.getsockname()[:2])
                except BlockingIOError:
                    pass
                finally:
                    client.setblocking(True)
                server, _addr = listener.accept()
                return server, client
            except Exception:
                client.close()
                raise
        finally:
            listener.close()

    socket.socketpair = _ipv6_socketpair
