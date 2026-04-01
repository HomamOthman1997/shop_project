from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any

import aiohttp

from config import settings

_LOCAL_HOSTS = {"localhost", "localhost.localdomain"}
_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".test", ".example", ".invalid")


@dataclass(slots=True)
class ProxyRiskDecision:
    decision: str
    reason: str
    endpoint: str
    host: str
    ip: str | None
    engines: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "endpoint": self.endpoint,
            "host": self.host,
            "ip": self.ip,
            "engines": dict(self.engines),
        }


def _split_host_port(endpoint: str) -> tuple[str, int | None]:
    value = str(endpoint or "").strip()
    if not value:
        return "", None
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0]
    if value.startswith("[") and "]" in value:
        end = value.index("]")
        host = value[1:end]
        port_raw = value[end + 1 :]
        if port_raw.startswith(":"):
            try:
                return host, int(port_raw[1:])
            except Exception:
                return host, -1
        return host, None
    if value.count(":") == 1:
        host, port_raw = value.rsplit(":", 1)
        if host:
            try:
                return host, int(port_raw)
            except Exception:
                return host, -1
    return value, None


def _extract_host(endpoint: str) -> str:
    host, _port = _split_host_port(endpoint)
    return host


def _parse_ip(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host))
    except Exception:
        return None


async def _resolve_host_ip(host: str) -> str | None:
    if not host:
        return None

    direct = _parse_ip(host)
    if direct:
        return direct

    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except Exception:
        return None

    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        candidate = sockaddr[0]
        parsed = _parse_ip(str(candidate))
        if parsed:
            return parsed
    return None


def _ip_quality(ip_raw: str | None) -> tuple[str, str]:
    if not ip_raw:
        return "gray", "ip_unresolved"
    try:
        ip_obj = ipaddress.ip_address(ip_raw)
    except Exception:
        return "gray", "invalid_ip"

    if not ip_obj.is_global:
        return "fail", "non_global_ip"
    return "gray", "global_ip_needs_reputation"


def _hostname_quality(host: str, port: int | None) -> tuple[str, str]:
    value = str(host or "").strip().lower().rstrip(".")
    if not value:
        return "fail", "missing_host"
    if "@" in value:
        return "fail", "userinfo_not_allowed"
    if value in _LOCAL_HOSTS:
        return "fail", "localhost_host"
    if any(value.endswith(suffix) for suffix in _LOCAL_SUFFIXES):
        return "fail", "local_suffix_host"
    if " " in value or "/" in value or "*" in value:
        return "fail", "invalid_host"
    if "_" in value:
        return "fail", "invalid_host"
    # For hostname values (not direct IP), enforce label syntax.
    if _parse_ip(value) is None:
        labels = [x for x in value.split(".") if x]
        if len(labels) < 2:
            return "fail", "invalid_host"
        label_re = re.compile(r"^[a-z0-9-]{1,63}$")
        for label in labels:
            if (not label_re.fullmatch(label)) or label.startswith("-") or label.endswith("-"):
                return "fail", "invalid_host"
    if port is not None and not (1 <= int(port) <= 65535):
        return "fail", "invalid_port"
    return "gray", "hostname_syntax_ok"


def _maxmind_stage(ip_raw: str | None) -> dict[str, Any]:
    # Placeholder stage with deterministic local checks.
    decision, reason = _ip_quality(ip_raw)
    return {"decision": decision, "reason": reason, "engine": "maxmind_local_gate"}


async def _ipqs_remote_stage(ip_raw: str) -> dict[str, Any]:
    key = str(getattr(settings, "proxy_ipqs_api_key", "") or "").strip()
    if not key:
        return {"decision": "gray", "reason": "ipqs_key_missing", "engine": "ipqs_remote"}
    timeout_sec = float(getattr(settings, "proxy_ipqs_timeout_sec", 4.0) or 4.0)
    timeout = aiohttp.ClientTimeout(total=max(1.0, min(timeout_sec, 15.0)))
    url = f"https://ipqualityscore.com/api/json/ip/{key}/{ip_raw}"
    params = {
        "strictness": "1",
        "allow_public_access_points": "true",
        "fast": "true",
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                payload = await resp.json(content_type=None)
                if resp.status >= 400 or not isinstance(payload, dict):
                    return {"decision": "gray", "reason": "ipqs_http_error", "engine": "ipqs_remote"}
    except Exception:
        return {"decision": "gray", "reason": "ipqs_request_failed", "engine": "ipqs_remote"}

    if payload.get("success") is False:
        return {"decision": "gray", "reason": "ipqs_unsuccessful", "engine": "ipqs_remote"}

    fraud_score = int(payload.get("fraud_score") or 0)
    is_proxy = bool(payload.get("proxy"))
    is_vpn = bool(payload.get("vpn")) or bool(payload.get("active_vpn"))
    is_tor = bool(payload.get("tor"))
    abuse_velocity = str(payload.get("abuse_velocity") or "").strip().lower()

    if is_tor:
        return {"decision": "fail", "reason": "ipqs_tor", "engine": "ipqs_remote", "fraud_score": fraud_score}
    if is_proxy or is_vpn:
        return {"decision": "fail", "reason": "ipqs_proxy_vpn", "engine": "ipqs_remote", "fraud_score": fraud_score}
    if fraud_score >= 90:
        return {"decision": "fail", "reason": "ipqs_high_fraud_score", "engine": "ipqs_remote", "fraud_score": fraud_score}
    if abuse_velocity in {"high", "very_high"}:
        return {"decision": "fail", "reason": "ipqs_abuse_velocity_high", "engine": "ipqs_remote", "fraud_score": fraud_score}
    if fraud_score <= 74:
        return {"decision": "pass", "reason": "ipqs_low_risk", "engine": "ipqs_remote", "fraud_score": fraud_score}
    return {"decision": "gray", "reason": "ipqs_medium_risk", "engine": "ipqs_remote", "fraud_score": fraud_score}


async def _ipqs_stage(ip_raw: str | None) -> dict[str, Any]:
    # Local placeholder fallback keeps behavior stable when no API key is set.
    if not ip_raw:
        return {"decision": "gray", "reason": "ip_unresolved", "engine": "ipqs_placeholder"}
    try:
        ip_obj = ipaddress.ip_address(ip_raw)
    except Exception:
        return {"decision": "gray", "reason": "invalid_ip", "engine": "ipqs_placeholder"}
    remote = await _ipqs_remote_stage(ip_raw)
    remote_decision = str(remote.get("decision") or "gray").lower()
    if remote_decision in {"pass", "fail"}:
        return remote
    if bool(getattr(settings, "proxy_ipqs_strict_fail_closed", False)):
        return {
            "decision": "fail",
            "reason": str(remote.get("reason") or "ipqs_gray_strict_fail_closed"),
            "engine": "ipqs_remote",
        }
    if ip_obj.is_global:
        return {"decision": "pass", "reason": "global_ip_passed_placeholder", "engine": "ipqs_placeholder"}
    return {"decision": "fail", "reason": "non_global_ip", "engine": "ipqs_placeholder"}


async def verify_proxy_endpoint(endpoint: str) -> dict[str, Any]:
    host, port = _split_host_port(endpoint)
    if not host:
        return ProxyRiskDecision(
            decision="fail",
            reason="missing_host",
            endpoint=str(endpoint or ""),
            host="",
            ip=None,
            engines={"maxmind": {"decision": "fail", "reason": "missing_host"}},
        ).to_dict()

    host_gate_decision, host_gate_reason = _hostname_quality(host, port)
    if host_gate_decision == "fail":
        return ProxyRiskDecision(
            decision="fail",
            reason=host_gate_reason,
            endpoint=str(endpoint or ""),
            host=host,
            ip=None,
            engines={"hostname": {"decision": "fail", "reason": host_gate_reason, "port": port}},
        ).to_dict()

    ip_raw = await _resolve_host_ip(host)

    maxmind_res = _maxmind_stage(ip_raw)
    maxmind_decision = str(maxmind_res.get("decision") or "gray").lower()
    engines: dict[str, Any] = {
        "hostname": {"decision": host_gate_decision, "reason": host_gate_reason, "port": port},
        "maxmind": maxmind_res,
    }

    if maxmind_decision == "pass":
        return ProxyRiskDecision(
            decision="pass",
            reason=str(maxmind_res.get("reason") or "maxmind_pass"),
            endpoint=str(endpoint or ""),
            host=host,
            ip=ip_raw,
            engines=engines,
        ).to_dict()

    if maxmind_decision == "fail":
        return ProxyRiskDecision(
            decision="fail",
            reason=str(maxmind_res.get("reason") or "maxmind_fail"),
            endpoint=str(endpoint or ""),
            host=host,
            ip=ip_raw,
            engines=engines,
        ).to_dict()

    # Gray path -> run secondary engine (IPQS stage).
    ipqs_res = await _ipqs_stage(ip_raw)
    engines["ipqs"] = ipqs_res
    ipqs_decision = str(ipqs_res.get("decision") or "gray").lower()

    if ipqs_decision == "pass":
        return ProxyRiskDecision(
            decision="pass",
            reason=str(ipqs_res.get("reason") or "ipqs_pass"),
            endpoint=str(endpoint or ""),
            host=host,
            ip=ip_raw,
            engines=engines,
        ).to_dict()

    if ipqs_decision == "fail":
        return ProxyRiskDecision(
            decision="fail",
            reason=str(ipqs_res.get("reason") or "ipqs_fail"),
            endpoint=str(endpoint or ""),
            host=host,
            ip=ip_raw,
            engines=engines,
        ).to_dict()

    return ProxyRiskDecision(
        decision="gray",
        reason=str(ipqs_res.get("reason") or "gray_after_ipqs"),
        endpoint=str(endpoint or ""),
        host=host,
        ip=ip_raw,
        engines=engines,
    ).to_dict()
