# Provider Timeout and Retry Matrix

Last updated: 2026-03-23

## Numbers providers

| Provider | Temp price timeout | Rental timeout | Retry policy |
|---|---:|---:|---|
| SMSPool | `numbers_provider_timeout_sec` (default 12s) | `numbers_rental_provider_timeout_sec` (default 10s, UI-capped) | 1 immediate attempt in manager path + provider internal fallback where implemented |
| TextVerified | `numbers_provider_timeout_sec` | `numbers_textverified_rental_timeout_sec` (default 8s, manager-capped) | tighter timeout to protect UI responsiveness |
| TellABot | `numbers_provider_timeout_sec` | N/A | same global timeout path |
| HeroSMS | `numbers_provider_timeout_sec` | `numbers_rental_provider_timeout_sec` | same global timeout path |
| SMS-Man | `numbers_provider_timeout_sec` | N/A | same global timeout path |

## Backoff policy

- Manager-level calls use bounded timeout and fail-fast behavior to avoid callback timeouts.
- Provider failures are normalized and surfaced with `provider_reason` when testing mode is enabled.
- Recovery and periodic sweeps are preferred for delayed consistency, not long blocking callbacks.

## Operational recommendation

1. Keep callback handlers under 10 seconds wall time.
2. Prefer retries in background sweeps over synchronous user callbacks.
3. Increase timeout only with matching provider SLA evidence.
