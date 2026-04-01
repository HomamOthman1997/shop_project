import asyncio
import json

from services.numbers.manager import get_provider_service_resolution_dynamic
from services.numbers.service_map import list_service_keys


CATALOG_PROVIDERS = ("smspool", "telabot", "textverified", "herosms", "smsman")


async def main() -> None:
    report: dict[str, dict[str, object]] = {}
    service_keys = list_service_keys()
    for provider_code in CATALOG_PROVIDERS:
        resolved = 0
        unresolved = 0
        dynamic = 0
        unresolved_samples: list[dict[str, str]] = []
        dynamic_samples: list[dict[str, str]] = []
        for service_key in service_keys:
            resolution = await get_provider_service_resolution_dynamic(service_key, provider_code)
            reason = str(resolution.get("provider_reason") or "")
            if resolution.get("resolved_provider_service") not in (None, ""):
                resolved += 1
                if reason not in {"resolved_static_mapping", "resolved_catalog_match", "resolved_live_catalog_match"}:
                    dynamic += 1
                    if len(dynamic_samples) < 20:
                        dynamic_samples.append(
                            {
                                "service_key": service_key,
                                "reason": reason,
                                "resolved": str(resolution.get("resolved_provider_service") or ""),
                                "candidate": str(resolution.get("resolved_provider_candidate") or ""),
                            }
                        )
                continue
            unresolved += 1
            if len(unresolved_samples) < 20:
                unresolved_samples.append(
                    {
                        "service_key": service_key,
                        "reason": reason,
                    }
                )

        report[provider_code] = {
            "resolved": resolved,
            "unresolved": unresolved,
            "dynamic_resolutions": dynamic,
            "dynamic_samples": dynamic_samples,
            "unresolved_samples": unresolved_samples,
        }

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
