from typing import Dict, Any, Optional

from services.numbers.core.session_manager import SessionManager
from .base_provider import BaseProvider
from config import settings
import logging

logger = logging.getLogger("telabot")

TELABOT_API = "https://www.tellabot.com/api_command.php"

# Do not cache credentials at import time; read from settings on each request so
# tests can monkeypatch them.



class TelabotProvider(BaseProvider):

    async def _get(self, params) -> Dict[str, Any]:
        session = await SessionManager.get_session()

        # read credentials dynamically
        user = settings.telabot_user
        key = settings.telabot_key
        if not user or not key:
            logger.error("Telabot credentials are missing (telabot_user/telabot_key)")
            return {"error": True, "raw": "missing_credentials"}

        params["user"] = user
        params["api_key"] = key

        try:
            async with session.get(TELABOT_API, params=params, timeout=8) as resp:
                return await resp.json()
        except Exception as exc:
            logger.warning("Telabot request failed: %s", exc)
            return {"error": True, "raw": str(exc)}

    async def list_services(self):
        # The API responds with a dict containing a ``status`` key and a
        # ``message`` list of service objects.  In other places (such as the
        # update_services utility) we expect a mapping from name→metadata, so
        # normalize here to make callers easier to write.
        resp = await self._get({"cmd": "list_services"})
        if isinstance(resp, dict) and "message" in resp and isinstance(resp["message"], list):
            # convert list to mapping keyed by service name
            return {item.get("name"): item for item in resp["message"] if item.get("name")}
        return resp

    async def get_price(self, service, country=None, state=None):
        # ``list_services`` may return either a mapping (our normalized form)
        # or something else; be robust.  If we received the raw ``status/message``
        # format we converted it above, so the simplest case is a dict keyed by
        # service name.  If we still have a list (unexpected) walk it as well.
        response = await self.list_services()

        if not response:
            return {"success": False, "raw": response}

        # if we somehow still got the unconverted payload, it would be a dict
        # with ``status`` and ``message`` list; we try to handle that gracefully
        if isinstance(response, dict) and "message" in response and isinstance(response["message"], list):
            for item in response["message"]:
                if item.get("name") == service:
                    price = item.get("price")
                    try:
                        price_val = float(price)
                    except Exception:
                        price_val = 0.0
                    return {
                        "success": True,
                        "price": price_val,
                        "api_service_name": service,
                        "provider_country": "us",
                        "provider_country_iso": "US",
                        "raw": item,
                    }
            return {"success": False, "raw": response}

        # otherwise assume a mapping
        if service not in response:
            return {"success": False, "raw": response}

        price = response[service].get("price")
        try:
            price_val = float(price)
        except Exception:
            price_val = 0.0

        return {
            "success": True,
            "price": price_val,
            "api_service_name": service,
            "provider_country": "us",
            "provider_country_iso": "US",
            "raw": response[service],
        }

    async def buy_number(
        self,
        service,
        country=None,
        state=None,
        mdn: Optional[str] = None,
        areacode: Optional[str] = None,
        markup: Optional[int] = None,
    ):
        params = {"cmd": "request", "service": service}
        if mdn:
            params["mdn"] = mdn
        if areacode:
            params["areacode"] = areacode
        if state and state != "none":
            params["state"] = state
        if markup is not None:
            params["markup"] = markup

        response = await self._get(params)

        if not isinstance(response, dict) or "message" not in response:
            logger.warning("unexpected telabot response for buy: %s", response)
            return {"success": False, "raw": response}

        message_payload = response.get("message")
        rows: list[dict] = []
        if isinstance(message_payload, list):
            rows = [item for item in message_payload if isinstance(item, dict)]
        elif isinstance(message_payload, dict):
            rows = [message_payload]
        else:
            # Telabot error payload often has message as plain string.
            return {"success": False, "raw": response}

        if not rows:
            return {"success": False, "raw": response}

        msg = rows[0]
        status = str(msg.get("status") or "").strip()
        if status in {"Reserved", "Awaiting MDN"}:
            return {
                "success": True,
                "order_id": msg.get("id"),
                "number": msg.get("mdn"),
                "raw": response,
            }

        logger.info("telabot buy returned status %s", status)
        return {"success": False, "raw": response}

    async def get_sms(self, activation_id) -> Dict[str, Any]:
        response = await self._get({"cmd": "read_sms", "id": activation_id})
        if not isinstance(response, dict):
            return {"success": False, "messages": [], "raw": response}
        status = str(response.get("status") or "").strip().lower()
        if response.get("error") or status in {"error", "failed", "failure"}:
            return {"success": False, "messages": [], "raw": response}
        payload = response.get("message")
        messages: list[str] = []
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if isinstance(row, str) and row.strip():
                messages.append(row.strip())
            elif isinstance(row, dict):
                for key in ("pin", "code", "reply", "text", "message"):
                    value = str(row.get(key) or "").strip()
                    if value:
                        messages.append(value)
                        break
        return {
            "success": bool(response),
            "messages": messages,
            "raw": response,
        }

    async def get_balance(self) -> Dict[str, Any]:
        return await self._get({"cmd": "balance"})

    async def cancel(self, activation_id) -> Dict[str, Any]:
        response = await self._get({"cmd": "reject", "id": activation_id})
        return {
            "success": response.get("status") == "ok",
            "raw": response,
        }
