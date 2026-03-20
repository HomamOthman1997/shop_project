from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Any


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


def _extract_host(endpoint: str) -> str:
    value = str(endpoint or "").strip()
    if not value:
        return ""
    if "://" in value:
        value = value.split("://", 1)[1]
    # Strip path/query if provider returned full URL-like endpoint.
    value = value.split("/", 1)[0]
    # IPv6 can be wrapped in [] and optional :port.
    if value.startswith("[") and "]" in value:
        return value[1 : value.index("]")]
    if ":" in value:
        host, _port = value.rsplit(":", 1)
        if host:
            return host
    return value


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


def _maxmind_stage(ip_raw: str | None) -> dict[str, Any]:
    # Placeholder stage with deterministic local checks.
    decision, reason = _ip_quality(ip_raw)
    return {"decision": decision, "reason": reason, "engine": "maxmind_local_gate"}


def _ipqs_stage(ip_raw: str | None) -> dict[str, Any]:
    # Placeholder stage for gray cases; keeps integration contract ready.
    if not ip_raw:
        return {"decision": "gray", "reason": "ip_unresolved", "engine": "ipqs_placeholder"}
    try:
        ip_obj = ipaddress.ip_address(ip_raw)
    except Exception:
        return {"decision": "gray", "reason": "invalid_ip", "engine": "ipqs_placeholder"}
    if ip_obj.is_global:
        return {"decision": "pass", "reason": "global_ip_passed_placeholder", "engine": "ipqs_placeholder"}
    return {"decision": "fail", "reason": "non_global_ip", "engine": "ipqs_placeholder"}


async def verify_proxy_endpoint(endpoint: str) -> dict[str, Any]:
    host = _extract_host(endpoint)
    if not host:
        return ProxyRiskDecision(
            decision="fail",
            reason="missing_host",
            endpoint=str(endpoint or ""),
            host="",
            ip=None,
            engines={"maxmind": {"decision": "fail", "reason": "missing_host"}},
        ).to_dict()

    ip_raw = await _resolve_host_ip(host)

    maxmind_res = _maxmind_stage(ip_raw)
    maxmind_decision = str(maxmind_res.get("decision") or "gray").lower()
    engines: dict[str, Any] = {"maxmind": maxmind_res}

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
    ipqs_res = _ipqs_stage(ip_raw)
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
